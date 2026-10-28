# RxGuard backend

All five steps of the RxGuard pipeline behind a FastAPI service: name normalisation, base
severity (DDInter, with an ML predictor for missing pairs), patient context, the rules engine, and
a RAG explainer that cites the FDA label passage behind every sentence.

## Run it (no external data needed)

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/make_dev_data.py          # spec example patients P-1042, P-2210 + seed pair
python -m pytest                          # 85 tests: every rule and boundary, spec example, ML, RAG, leakage
uvicorn rxguard.api.main:app --reload     # http://localhost:8000/docs
```

```bash
curl -X POST localhost:8000/check -H 'content-type: application/json' \
  -d '{"drug_a":"Tylenol","drug_b":"Warfarin","patient_id":"P-1042"}'   # -> 9, High
```

Swap `P-1042` for `P-2210` and the same pair scores 4, Moderate.

## API

| Endpoint | Purpose |
|---|---|
| `POST /check` | `{drug_a, drug_b, patient_id, explain?}` → full risk report. `explain: false` skips step 5 for a sub-second score |
| `POST /explain` | `{drug_a, drug_b}` → cited explanation only (no patient data involved) |
| `GET /drugs?q=war` | Autocomplete suggestions for medicine names |
| `GET /patients` | Patient list for the picker |
| `GET /health` | Interaction pairs loaded, whether the ML model is loaded, retriever, LLM provider, labelled drugs |

## What's built

| Step | Module | Status |
|---|---|---|
| 1 Normalise | `rxguard/normalise/rxnorm.py` | RxNav API + disk cache + offline alias fallback; ≤3 suggestions; combination products split into ingredients (FR-02, FR-03, NFR-07) |
| 2 Base severity | `rxguard/interactions/store.py` | SQLite store + DDInter CSV loader; pairs not in DDInter go to the ML predictor, with the 0.6 confidence floor (FR-04, NFR-03) |
| 2 ML predictor | `rxguard/ml/` | Morgan fingerprints (RDKit) from PubChem SMILES, symmetric pair features, HistGradientBoosting (or XGBoost/RF), drug-level split, baselines, Major guard (FR-05, NFR-02) |
| 3 Patient context | `rxguard/patients/fhir.py` | Parses FHIR bundles from HAPI (`$everything`) or local files: age, active conditions, latest eGFR / ALT / alcohol (FR-06, FR-07) |
| 4 Risk score | `rxguard/rules/engine.py` | All rules from `config/rules.yaml`, per-drug flags from `config/drug_flags.yaml`, line-by-line breakdown, cap, bands, missing fields flagged (FR-08–FR-10, NFR-05) |
| 5 Explain | `rxguard/explain/` | openFDA labels split into section-tagged passages; ChromaDB + MiniLM or TF-IDF retrieval; Gemini / Groq / Ollama / no-LLM extractive mode; citation check drops any uncited sentence (FR-11–13, NFR-04, NFR-06, NFR-09, NFR-10) |

### ML severity predictor (FR-05)

- **Features.** Each drug becomes a 1024-bit Morgan fingerprint (radius 2). A pair is `fp_a + fp_b`
  (0/1/2 per bit), so (A, B) and (B, A) always get the same prediction.
- **Evaluation.** 20% of drugs are held out; every test pair includes at least one drug the model
  never saw (the spec's "split by drug"). Reported against majority-class and logistic-regression
  baselines: macro F1, per-class precision/recall, Major recall.
- **Major guard (NFR-02).** If the most likely class is Moderate/Minor but P(Major) is above a
  guard tuned on a validation split, the pair is shown as "Unknown — consult a pharmacist"
  instead. `major_safe_recall` in the metrics is the share of true Majors never shown as
  something milder; the guard is tuned so it reaches 0.90.
- **Runtime.** The saved model carries every known drug's fingerprint, so the API needs no RDKit.
  Drugs without a SMILES (biologics) or unseen by the model return Unknown.

### RAG explainer (FR-11–13)

- **Knowledge base.** For each drug, the best openFDA label (single-ingredient, has an
  interactions section, most recent) is split into ~120-word passages tagged with drug and
  section: Drug Interactions, Warnings (and Precautions), Boxed Warning, Contraindications,
  Mechanism of Action, and the OTC sections such as "Ask a Doctor or Pharmacist".
- **Retrieval.** Each drug's own label is searched; passages that name the other drug and passages
  from interaction sections are boosted; at least 2 come from each label (top 6 in total).
- **Generation.** The LLM gets the two ingredient names, the database severity as context, and the
  numbered passages — never patient data (NFR-06). It returns JSON items, each citing passage ids.
- **Citation check (FR-13).** Items with no citation, or citing an id outside the retrieved set, are
  dropped and listed under `explanation.dropped`. The UI shows numbered sources with the passage
  text, so every sentence can be checked.
- **No key needed.** With no LLM configured (or if the call fails) the explainer quotes the label
  sentences that name the other drug, each cited. If the labels don't describe the pair, it says
  so rather than inventing anything. LLM answers are cached per pair.
- **Switching provider (NFR-10).** `config/explainer.yaml` → `provider: gemini | groq | ollama | extractive`,
  or set `RXGUARD_LLM_PROVIDER`. Keys come from `GEMINI_API_KEY` / `GROQ_API_KEY`.

Response fields: `mechanism`, `monitoring`, `affected_systems`, `citations` (as in the spec), plus
`explanation` with `status`, `provider`, `sentences` (each with source numbers), `sources`
(citation + passage text), `retrieved`, `dropped` and `latency_ms`.

## Loading real data

Run these once, in order, from `backend/` (they need internet; the API itself runs offline after).

```bash
# 1. Interactions (DDInter CSVs, academic licence)
python scripts/load_ddinter.py data/raw/ddinter/*.csv

# 2. ML predictor: SMILES from PubChem, then train + evaluate (~15–30 min for all pairs)
pip install -r requirements-ml.txt
python scripts/fetch_smiles.py                 # data/smiles.json, resumable
python scripts/train_predictor.py              # data/models/severity_model.joblib + severity_metrics.json
#   options: --model xgboost | rf   --max-pairs 50000 (less memory)

# 3. FDA labels for the explainer
python scripts/fetch_labels.py --top 150       # drug_flags.yaml drugs + 150 most common DDInter drugs
pip install -r requirements-rag.txt            # optional: embeddings instead of TF-IDF
python scripts/build_label_index.py            # data/labels/chroma/

# 4. LLM (optional; without one the explainer quotes label sentences)
export GEMINI_API_KEY=...                      # free key from Google AI Studio, or GROQ_API_KEY=...

# 5. Patients (Synthea)
python scripts/add_alcohol.py <synthea>/output/fhir   # then POST bundles to HAPI
export RXGUARD_FHIR_URL=http://localhost:8080/fhir

# 6. Evaluate the explainer (extend eval/retrieval_questions.csv to 100 rows)
python scripts/eval_explainer.py --questions eval/retrieval_questions.csv
```

`docker compose up --build` starts HAPI FHIR and the API together; the `data/` folder (model,
labels, store) is mounted into the container.

## Design notes

- A liver-disease condition feeds the liver rule only, never also a condition caution, so it
  isn't counted twice (matches the spec's P-1042 breakdown).
- A condition listed as a caution for both drugs adds +2 once.
- For combination products, the worst ingredient pair is scored; an unknown pair ranks above a
  known Moderate/Minor so it can't be hidden.
- A drug not in `drug_flags.yaml` gets base severity plus age only, and is listed in `missing_fields`.
- `drug_flags.yaml` is seed data (9 drugs, all `verified: false`) — every entry must be checked
  against its FDA label before submission. ALT upper limit (40 U/L) is a config value to confirm.
