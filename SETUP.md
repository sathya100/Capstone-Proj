# SafeRx — Local Environment Setup

## Prerequisites
- Python 3.11
- (Optional) conda/miniconda if using `environment.yml`
- An Anthropic API key for the Claude API (explanation generation + verification)

## Option A: pip + venv
```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Option B: conda
```bash
conda env create -f environment.yml
conda activate saferx
```

## Environment variables
Create a `.env` file in the project root (do NOT commit this file):
```
ANTHROPIC_API_KEY=your_key_here
```

## Verify install
```bash
python -c "import xgboost, faiss, sklearn, anthropic; print('OK')"
```

## Repository structure (planned)
```
Capstone-Proj/
├── data/                 # curated DDI dataset (raw + processed), not committed if large/licensed
├── src/
│   ├── ml/               # classifier training + evaluation
│   ├── retrieval/        # embedding index / RAG retrieval
│   ├── generation/       # LLM explanation generation
│   ├── verification/     # hallucination-detection / claim-checking layer
│   └── api/              # backend API (Flask)
├── frontend/             # web interface (React or Streamlit)
├── notebooks/            # exploratory analysis
├── tests/
├── requirements.txt
├── environment.yml
├── SETUP.md
└── SEMESTER_ROADMAP.md
```

## Status (as of Sep 16, 2026)
- [ ] Repo initialized with folder structure above
- [ ] Dataset access confirmed (DrugBank DDI and/or TWOSIDES/DDI Corpus)
- [ ] Environment verified on local machine
- [ ] Advisor assigned and repo access shared
