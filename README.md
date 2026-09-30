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
 5. Explanation          RAG over FDA labels + LLM, cited      (planned)
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
├── backend/                 Python / FastAPI service (steps 1–4)
│   ├── rxguard/
│   │   ├── normalise/       Step 1 — RxNorm name normalisation
│   │   ├── interactions/    Step 2 — DDInter store + ML predictor hook
│   │   ├── patients/        Step 3 — FHIR patient context
│   │   ├── rules/           Step 4 — risk scoring engine
│   │   ├── api/             HTTP API (POST /check)
│   │   ├── pipeline.py      Runs the steps in order
│   │   └── models.py        Shared data types
│   ├── config/              Scoring rules and per-drug flags (YAML)
│   ├── scripts/             Offline data pipelines
│   ├── tests/               Unit and end-to-end tests
│   └── README.md            Backend details
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

Or with Docker (API + HAPI FHIR server): `cd backend && docker compose up --build`

## Status

| Component | Requirements | Status |
|---|---|---|
| Name normalisation | FR-01–03 | ✅ Done |
| Interaction store (DDInter) | FR-04 | ✅ Done — real DDInter data not yet loaded |
| ML severity predictor | FR-05 | ⏳ Planned (weeks 3–4) |
| Patient context (FHIR) | FR-06–07 | ✅ Done — Synthea patients not yet generated |
| Rules engine | FR-08–10 | ✅ Done, 43 tests passing |
| RAG explainer | FR-11–13 | ⏳ Planned (weeks 6–7) |
| Web UI | FR-14–16 | ⏳ Planned (weeks 9–10) |

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
