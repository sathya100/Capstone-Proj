# RxGuard — Personalized Drug Interaction Checker

RxGuard tells a clinician or caregiver how risky it is for **one specific patient** to take two
medicines together, as a 0–10 score with the reasons behind every point.

Standard interaction checkers give the same answer for every patient. RxGuard adjusts the risk
using the patient's age, conditions, kidney and liver labs, and alcohol use — with transparent
rules, so every point can be explained.

> Clinical decision support only. Not medical advice. Uses synthetic patients (Synthea) only.

## How it works

```
drug A + drug B + patient ID
        │
        ▼
 1. Normalise names      RxNorm (Tylenol → acetaminophen)
 2. Base severity        DDInter database, ML model for unknown pairs
 3. Patient context      FHIR server with Synthea patients
 4. Risk score           config-driven rules → 0–10 + breakdown
 5. Explanation          RAG over FDA labels + LLM, every sentence cited
        │
        ▼
 JSON risk report → web UI
```

Example — Tylenol + Warfarin:

| Patient | Profile | Score |
|---|---|---|
| P-1042 | 68, chronic liver disease, 4 drinks/day | **9 — High** |
| P-2210 | 30, no conditions, no alcohol | **4 — Moderate** |

## Repository layout

```
Capstone-Proj/
├── backend/                 Python / FastAPI service (all five steps)
│   ├── rxguard/
│   │   ├── normalise/       Step 1 — RxNorm name normalisation
│   │   ├── interactions/    Step 2 — DDInter store
│   │   ├── ml/              Step 2 — ML severity predictor for pairs missing from DDInter
│   │   ├── patients/        Step 3 — FHIR patient context
│   │   ├── rules/           Step 4 — risk scoring engine
│   │   ├── explain/         Step 5 — RAG explainer: FDA label passages, LLM, citation check
│   │   ├── api/             HTTP API (POST /check)
│   │   ├── pipeline.py      Runs the steps in order
│   │   └── models.py        Shared data types
│   ├── config/              Scoring rules, per-drug flags, explainer/LLM settings (YAML)
│   ├── scripts/             Offline data pipelines
│   ├── tests/               Unit and end-to-end tests
│   └── README.md            Backend details
├── frontend/                React + Vite web UI
│   ├── src/components/      Gauge, breakdown, body map, inputs
│   └── README.md            Frontend details
├── docs/
│   └── RxGuard_Requirements_Architecture.pdf
└── .github/workflows/       CI: runs the tests on every push
```

## Quick start

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/make_dev_data.py          # demo patients + seed interaction
python -m pytest                          # run the tests
uvicorn rxguard.api.main:app --reload     # API docs at http://localhost:8000/docs
```

Then the web UI, in a second terminal:

```bash
cd frontend
npm install
npm run dev                               # http://localhost:5173
```

Click "Try the example" to see the same drug pair scored for two patients side by side.

Or run the backend with Docker (API + HAPI FHIR server): `cd backend && docker compose up --build`

## Status

| Component | Requirements | Status |
|---|---|---|
| Name normalisation | FR-01–03 | ✅ Done |
| Interaction store (DDInter) | FR-04 | ✅ Done — real DDInter data not yet loaded |
| ML severity predictor | FR-05 | ✅ Trained on real DDInter data (261 drugs, 16,073 pairs): Random Forest macro F1 0.685 on unseen drugs vs 0.272 baseline — [results](docs/ml_results.html) |
| Patient context (FHIR) | FR-06–07 | ✅ Done — Synthea patients not yet generated |
| Rules engine | FR-08–10 | ✅ Done |
| RAG explainer | FR-11–13 | ✅ Code done — run `fetch_labels.py` to download the FDA labels |
| Web UI | FR-14–17 | ✅ Done — score first, cited explanation streams in after |
| Evaluation | — | ML metrics in `docs/results/`; explainer metrics pending FDA labels |

76 backend tests pass. Remaining work is data and measurement: load DDInter, fetch SMILES and FDA
labels, generate Synthea patients, verify `drug_flags.yaml`, then run the evaluation. See
[backend/README.md](backend/README.md#loading-real-data) for the commands.

## Data sources

All free for academic use; data files are not committed to this repo.

| Source | Used for |
|---|---|
| [RxNorm / RxNav](https://lhncbc.nlm.nih.gov/RxNav/) (NLM) | Drug name normalisation |
| [DDInter](https://ddinter.scbdd.com/) | Interaction severity (ground truth) |
| [openFDA drug labels](https://open.fda.gov/apis/drug/label/) | RAG knowledge base, drug flags |
| [PubChem](https://pubchem.ncbi.nlm.nih.gov/) | Molecular structures for ML features |
| [Synthea](https://synthetichealth.github.io/synthea/) | Synthetic FHIR patients |

## Documentation

- [Requirements, datasets & architecture](docs/RxGuard_Requirements_Architecture.pdf)
- [Backend README](backend/README.md)
