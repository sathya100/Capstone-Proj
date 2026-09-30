# RxGuard backend

Steps 1–4 of the five-step pipeline in the RxGuard spec, with a FastAPI `/check` endpoint.
Step 5 (RAG explainer) and the ML predictor plug in later through the `explainer` and
`predictor` hooks in `rxguard/pipeline.py`.

## Run it (no external data needed)

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/make_dev_data.py          # spec example patients P-1042, P-2210 + seed pair
python -m pytest                          # 43 tests: every rule and boundary + spec example
uvicorn rxguard.api.main:app --reload     # http://localhost:8000/docs
```

```bash
curl -X POST localhost:8000/check -H 'content-type: application/json' \
  -d '{"drug_a":"Tylenol","drug_b":"Warfarin","patient_id":"P-1042"}'   # -> 9, High
```

Swap `P-1042` for `P-2210` and the same pair scores 4, Moderate.

## What's built

| Step | Module | Status |
|---|---|---|
| 1 Normalise | `rxguard/normalise/rxnorm.py` | RxNav API + disk cache + offline alias fallback; ≤3 suggestions; combination products split into ingredients (FR-02, FR-03, NFR-07) |
| 2 Base severity | `rxguard/interactions/store.py` | SQLite store + DDInter CSV loader; ML predictor hook with the 0.6 confidence floor (FR-04, NFR-03). Predictor itself is a stub that returns unknown |
| 3 Patient context | `rxguard/patients/fhir.py` | Parses FHIR bundles from HAPI (`$everything`) or local files: age, active conditions, latest eGFR / ALT / alcohol (FR-06, FR-07) |
| 4 Risk score | `rxguard/rules/engine.py` | All rules from `config/rules.yaml`, per-drug flags from `config/drug_flags.yaml`, line-by-line breakdown, cap, bands, missing fields flagged (FR-08–FR-10, NFR-05) |
| 5 Explain | — | Not started; response carries empty `mechanism` / `citations` fields |

## Loading real data

- **DDInter:** download the CSVs, then `python scripts/load_ddinter.py data/raw/ddinter/*.csv`
- **Synthea:** generate patients, run `python scripts/add_alcohol.py <synthea>/output/fhir`, POST
  the bundles to HAPI, and set `RXGUARD_FHIR_URL=http://localhost:8080/fhir`
- `docker compose up --build` starts HAPI FHIR and the API together

## Design notes

- A liver-disease condition feeds the liver rule only, never also a condition caution, so it
  isn't counted twice (matches the spec's P-1042 breakdown).
- A condition listed as a caution for both drugs adds +2 once.
- For combination products, the worst ingredient pair is scored; an unknown pair ranks above a
  known Moderate/Minor so it can't be hidden.
- A drug not in `drug_flags.yaml` gets base severity plus age only, and is listed in `missing_fields`.
- `drug_flags.yaml` is seed data (9 drugs, all `verified: false`) — every entry must be checked
  against its FDA label before submission. ALT upper limit (40 U/L) is a config value to confirm.
