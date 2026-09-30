"""FastAPI orchestrator: runs the five fixed steps and returns one JSON report."""
from __future__ import annotations

import os
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any, Optional

from rxguard.interactions.store import InteractionStore, NoModelPredictor, SeverityPredictor, base_severity
from rxguard.models import SeverityResult
from rxguard.normalise.rxnorm import RxNormNormaliser
from rxguard.rules.engine import RulesEngine

DISCLAIMER = "Clinical decision support only. Not medical advice."
SEVERITY_RANK = {"Major": 3, "Moderate": 2, "Minor": 1, "None": 0}


class CheckError(Exception):
    def __init__(self, status: int, detail: Any):
        self.status, self.detail = status, detail


class Pipeline:
    def __init__(self, normaliser: RxNormNormaliser, store: InteractionStore, patients,
                 engine: RulesEngine, predictor: Optional[SeverityPredictor] = None, explainer=None):
        self.normaliser = normaliser
        self.store = store
        self.patients = patients
        self.engine = engine
        self.predictor = predictor or NoModelPredictor()
        self.explainer = explainer

    def check(self, drug_a: str, drug_b: str, patient_id: str) -> dict[str, Any]:
        # 1. Normalise
        na, nb = self.normaliser.normalise(drug_a), self.normaliser.normalise(drug_b)
        unresolved = [{"query": n.query, "suggestions": n.suggestions} for n in (na, nb) if not n.found]
        if unresolved:
            raise CheckError(422, {"error": "unknown_drug_name", "unresolved": unresolved})

        # 2. Base severity — every ingredient pair for combination products; keep the worst
        min_conf = self.engine.rules["ml"]["min_confidence"]
        best: Optional[tuple[str, str, SeverityResult]] = None
        for ia, ib in product(na.ingredients, nb.ingredients):
            if ia == ib:
                continue
            sev = base_severity(self.store, self.predictor, ia, ib, min_conf)
            if best is None or _worse(sev, best[2]):
                best = (ia, ib, sev)
        if best is None:
            raise CheckError(422, {"error": "same_ingredient", "detail": "Both names map to the same ingredient."})
        ia, ib, sev = best

        # 3. Patient context
        patient = self.patients.get(patient_id)
        if patient is None:
            raise CheckError(404, {"error": "patient_not_found", "patient_id": patient_id})

        # 4. Risk score
        risk = self.engine.score([ia, ib], sev, patient)

        # 5. Explanation (RAG + LLM) — not built yet
        explanation = self.explainer.explain(ia, ib, sev, risk) if self.explainer else {
            "mechanism": None, "affected_systems": [], "monitoring": [], "citations": [],
            "status": "explainer not implemented yet (weeks 6–7)",
        }

        return {
            "drugs": [ia, ib],
            "input_names": [drug_a, drug_b],
            "ingredients": {drug_a: na.ingredients, drug_b: nb.ingredients},
            "base_severity": sev.severity or "Unknown",
            "severity_source": sev.source,
            "severity_confidence": sev.confidence,
            "risk_score": risk.risk_score,
            "risk_level": risk.risk_level,
            "score_breakdown": [{"reason": l.reason, "points": l.points, "rule": l.rule} for l in risk.breakdown],
            "score_capped": risk.capped,
            "missing_fields": risk.missing_fields,
            "patient": {k: v for k, v in asdict(patient).items() if k != "conditions"}
                       | {"conditions": [c.display for c in patient.conditions]},
            **explanation,
            "disclaimer": DISCLAIMER,
        }


def _worse(a: SeverityResult, b: SeverityResult) -> bool:
    """Unknown ranks just below Major, so it is never hidden behind a known Moderate/Minor (NFR-03)."""
    ra = 2.5 if a.severity is None else SEVERITY_RANK[a.severity]
    rb = 2.5 if b.severity is None else SEVERITY_RANK[b.severity]
    return ra > rb


def build_default_pipeline() -> Pipeline:
    from rxguard.patients.fhir import FhirPatientSource, FilePatientSource

    root = Path(__file__).resolve().parents[1]
    data = Path(os.getenv("RXGUARD_DATA", root / "data"))
    store = InteractionStore(os.getenv("RXGUARD_DB", data / "interactions.sqlite"))
    fhir_url = os.getenv("RXGUARD_FHIR_URL")
    patients = FhirPatientSource(fhir_url) if fhir_url else FilePatientSource(data / "patients")
    normaliser = RxNormNormaliser(cache_path=data / "cache" / "rxnorm.json",
                                  offline=os.getenv("RXGUARD_OFFLINE") == "1")
    return Pipeline(normaliser, store, patients, RulesEngine.from_config())
