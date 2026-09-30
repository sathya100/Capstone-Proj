"""HTTP API. Run: uvicorn rxguard.api.main:app --reload  (from backend/)"""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rxguard.pipeline import CheckError, Pipeline, build_default_pipeline

app = FastAPI(title="RxGuard", version="0.1.0",
              description="Personalized drug interaction checker. Clinical decision support only. Not medical advice.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class CheckRequest(BaseModel):
    drug_a: str = Field(..., min_length=1, examples=["Tylenol"])
    drug_b: str = Field(..., min_length=1, examples=["Warfarin"])
    patient_id: str = Field(..., min_length=1, examples=["P-1042"])


@lru_cache
def get_pipeline() -> Pipeline:
    return build_default_pipeline()


@app.get("/health")
def health(p: Pipeline = Depends(get_pipeline)):
    return {"status": "ok", "interaction_pairs": p.store.count()}


@app.post("/check")
def check(req: CheckRequest, p: Pipeline = Depends(get_pipeline)):
    try:
        return p.check(req.drug_a, req.drug_b, req.patient_id)
    except CheckError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
