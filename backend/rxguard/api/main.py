"""HTTP API. Run: uvicorn rxguard.api.main:app --reload  (from backend/)"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rxguard.pipeline import CheckError, Pipeline, build_default_pipeline

app = FastAPI(title="RxGuard", version="0.2.0",
              description="Personalized drug interaction checker. Clinical decision support only. Not medical advice.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class CheckRequest(BaseModel):
    drug_a: str = Field(..., min_length=1, examples=["Tylenol"])
    drug_b: str = Field(..., min_length=1, examples=["Warfarin"])
    patient_id: str = Field(..., min_length=1, examples=["P-1042"])
    explain: bool = Field(True, description="Include the FDA-label explanation. Set false to get the "
                                            "score fast and fetch the explanation from POST /explain (NFR-01).")


class ExplainRequest(BaseModel):
    drug_a: str = Field(..., min_length=1, examples=["acetaminophen"])
    drug_b: str = Field(..., min_length=1, examples=["warfarin"])


@lru_cache
def get_pipeline() -> Pipeline:
    return build_default_pipeline()


@app.get("/health")
def health(p: Pipeline = Depends(get_pipeline)):
    ex = p.explainer
    return {
        "status": "ok",
        "interaction_pairs": p.store.count(),
        "severity_model": type(p.predictor).__name__ != "NoModelPredictor",
        "explainer": None if ex is None else {
            "retriever": ex.retriever.name,
            "provider": ex.llm.name if ex.llm else "extractive",
            "labelled_drugs": len(ex.retriever.drugs()),
        },
    }


@app.post("/check")
def check(req: CheckRequest, p: Pipeline = Depends(get_pipeline)):
    try:
        return p.check(req.drug_a, req.drug_b, req.patient_id, explain=req.explain)
    except CheckError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@app.post("/explain")
def explain(req: ExplainRequest, p: Pipeline = Depends(get_pipeline)):
    """Step 5 only: cited explanation for an ingredient pair. No patient data is involved (NFR-06)."""
    try:
        return p.explain(req.drug_a, req.drug_b)
    except CheckError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@app.get("/drugs")
def drugs(q: str = Query("", max_length=60), p: Pipeline = Depends(get_pipeline)):
    return {"suggestions": p.suggest_drugs(q)}


@app.get("/patients")
def patients(p: Pipeline = Depends(get_pipeline)):
    return {"patients": p.list_patients()}
