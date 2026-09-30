"""Step 3: patient context from a FHIR R4 server loaded with Synthea data (FR-06, FR-07).

Works from a FHIR Bundle, so the same parser serves the HAPI server ($everything) and local
fixture files for development and tests.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx

from rxguard.models import Condition, PatientContext

# LOINC codes. Synthea emits 33914-3 for eGFR; the others cover CKD-EPI variants.
EGFR_CODES = {"33914-3", "62238-1", "98979-8", "69405-9"}
ALT_CODES = {"1742-6"}
# Synthea does not reliably record alcohol use; scripts/add_alcohol.py adds this observation.
ALCOHOL_SYSTEM = "https://rxguard.example/fhir/CodeSystem/observations"
ALCOHOL_CODE = "alcohol-drinks-per-day"


def _age(birth: str, today: Optional[date] = None) -> int:
    today = today or date.today()
    b = date.fromisoformat(birth[:10])
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def _codes(resource: dict[str, Any]) -> set[str]:
    return {c.get("code") for c in resource.get("code", {}).get("coding", []) if c.get("code")}


def _is_active(cond: dict[str, Any]) -> bool:
    status = {c.get("code") for c in cond.get("clinicalStatus", {}).get("coding", [])}
    return not status or "active" in status or "recurrence" in status or "relapse" in status


def parse_bundle(patient_id: str, bundle: dict[str, Any], today: Optional[date] = None) -> PatientContext:
    ctx = PatientContext(patient_id=patient_id)
    latest: dict[str, tuple[str, float]] = {}  # field -> (effective datetime, value)

    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType")
        if rtype == "Patient" and res.get("birthDate"):
            ctx.age = _age(res["birthDate"], today)
        elif rtype == "Condition" and _is_active(res):
            coding = (res.get("code", {}).get("coding") or [{}])[0]
            display = res.get("code", {}).get("text") or coding.get("display") or ""
            ctx.conditions.append(Condition(display=display, code=coding.get("code")))
        elif rtype == "Observation":
            codes = _codes(res)
            value = res.get("valueQuantity", {}).get("value")
            if value is None:
                continue
            when = res.get("effectiveDateTime") or res.get("issued") or ""
            field = ("egfr" if codes & EGFR_CODES else "alt" if codes & ALT_CODES
                     else "alcohol_drinks_per_day" if ALCOHOL_CODE in codes else None)
            if field and (field not in latest or when > latest[field][0]):
                latest[field] = (when, float(value))

    for field, (_, value) in latest.items():
        setattr(ctx, field, value)
    return ctx


def summary(ctx: PatientContext) -> dict[str, Any]:
    return {"patient_id": ctx.patient_id, "age": ctx.age, "conditions": [c.display for c in ctx.conditions]}


class FhirPatientSource:
    """Fetch from a FHIR server, e.g. HAPI at http://localhost:8080/fhir."""

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def get(self, patient_id: str) -> Optional[PatientContext]:
        resp = self.client.get(f"{self.base_url}/Patient/{patient_id}/$everything", params={"_count": 1000})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return parse_bundle(patient_id, resp.json())

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        """Patient picker: ids and ages only (conditions need one request per patient)."""
        resp = self.client.get(f"{self.base_url}/Patient", params={"_count": limit, "_elements": "id,birthDate"})
        resp.raise_for_status()
        out = []
        for e in resp.json().get("entry", []):
            r = e["resource"]
            out.append({"patient_id": r["id"], "age": _age(r["birthDate"]) if r.get("birthDate") else None,
                        "conditions": []})
        return out


class FilePatientSource:
    """Read <patient_id>.json FHIR bundles from a folder (dev and tests)."""

    def __init__(self, folder: Path | str, today: Optional[date] = None):
        self.folder = Path(folder)
        self.today = today

    def get(self, patient_id: str) -> Optional[PatientContext]:
        path = self.folder / f"{patient_id}.json"
        if not path.exists():
            return None
        return parse_bundle(patient_id, json.loads(path.read_text()), self.today)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.folder.glob("*.json"))[:limit]:
            ctx = self.get(path.stem)
            if ctx:
                out.append(summary(ctx))
        return out
