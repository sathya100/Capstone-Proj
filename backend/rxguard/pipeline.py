"""FastAPI orchestrator: runs the five fixed steps and returns one JSON report."""
from __future__ import annotations

import os
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any, Optional

from rxguard.interactions.store import InteractionStore, NoModelPredictor, SeverityPredictor, base_severity
from rxguard.models import SeverityResult
from rxguard.normalise.rxnorm import OFFLINE_ALIASES, RxNormNormaliser
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

    def suggest_drugs(self, q: str, limit: int = 8) -> list[str]:
        """Autocomplete (FR-01): known brand/generic names and every drug in the interaction store."""
        q = q.strip().lower()
        if not q:
            return []
        names = set(OFFLINE_ALIASES) | set(self.engine.drugs) | set(self.store.drug_names(q, 50))
        starts = sorted(n for n in names if n.startswith(q))
        contains = sorted(n for n in names if q in n and not n.startswith(q))
        return (starts + contains)[:limit]

    def list_patients(self) -> list[dict[str, Any]]:
        return self.patients.list()

    def check(self, drug_a: str, drug_b: str, patient_id: str, explain: bool = True) -> dict[str, Any]:
        """Full report. With explain=False step 5 is skipped so the score returns fast (NFR-01);
        the UI then fetches the explanation separately from explain()."""
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

        # 5. Explanation (RAG over FDA labels + LLM). Only drug names and severity are passed —
        #    never patient data (NFR-06).
        explanation = self._explain(ia, ib, sev.severity) if explain else _empty_explanation("pending")

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


    def explain(self, drug_a: str, drug_b: str) -> dict[str, Any]:
        """Step 5 on its own, for POST /explain. Takes ingredient names as returned by check()."""
        na, nb = self.normaliser.normalise(drug_a), self.normaliser.normalise(drug_b)
        if not (na.found and nb.found):
            raise CheckError(422, {"error": "unknown_drug_name"})
        ia, ib = na.ingredients[0], nb.ingredients[0]
        sev = self.store.lookup(ia, ib)
        return {"drugs": [ia, ib], **self._explain(ia, ib, sev), "disclaimer": DISCLAIMER}

    def _explain(self, a: str, b: str, severity: Optional[str]) -> dict[str, Any]:
        if self.explainer is None:
            return _empty_explanation("explainer not configured")
        try:
            return self.explainer.explain(a, b, severity)
        except Exception as e:  # an explanation failure must never block the score
            return _empty_explanation(f"explainer error: {type(e).__name__}")


def _empty_explanation(status: str) -> dict[str, Any]:
    return {"mechanism": None, "affected_systems": [], "monitoring": [], "citations": [],
            "explanation": {"status": status, "sentences": [], "passages": []}}


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

    # Step 2 fallback: trained severity model, if scripts/train_predictor.py has been run (FR-05)
    predictor: Optional[SeverityPredictor] = None
    model_path = Path(os.getenv("RXGUARD_MODEL", data / "models" / "severity_model.joblib"))
    if model_path.exists():
        from rxguard.ml.predictor import MLPredictor
        predictor = MLPredictor.load(model_path)

    # Step 5: RAG explainer over FDA label passages (FR-11–13)
    from rxguard.explain.explainer import build_explainer
    explainer = build_explainer(data)

    return Pipeline(normaliser, store, patients, RulesEngine.from_config(), predictor, explainer)
