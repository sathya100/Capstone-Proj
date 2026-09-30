"""Offline pipeline 5 (part): add a drinks-per-day Observation to each Synthea patient bundle.

Synthea does not reliably record alcohol use, so this script adds one synthetic observation per
patient (state this in the report). Deterministic per patient via a seeded RNG.

    python scripts/add_alcohol.py path/to/synthea/output/fhir  [--seed 42]

Edits the transaction bundles in place, ready to POST to the HAPI FHIR server.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.patients.fhir import ALCOHOL_CODE, ALCOHOL_SYSTEM  # noqa: E402

# Rough adult distribution (a design assumption to document): most drink little or nothing,
# a minority drink 3+ per day so the alcohol rule is exercised in evaluation.
BUCKETS = [(0.55, (0, 0)), (0.30, (1, 2)), (0.15, (3, 6))]


def sample(rng: random.Random) -> int:
    x, acc = rng.random(), 0.0
    for p, (lo, hi) in BUCKETS:
        acc += p
        if x < acc:
            return rng.randint(lo, hi)
    return 0


def process(path: Path, seed: int) -> bool:
    b = json.loads(path.read_text())
    patient = next((e for e in b.get("entry", []) if e["resource"]["resourceType"] == "Patient"), None)
    if patient is None:
        return False
    if any(ALCOHOL_CODE in json.dumps(e["resource"].get("code", {})) for e in b["entry"]):
        return False  # already added
    pid = patient["resource"]["id"]
    rng = random.Random(f"{seed}-{pid}")
    b["entry"].append({
        "fullUrl": f"urn:uuid:alcohol-{pid}",
        "resource": {
            "resourceType": "Observation", "status": "final",
            "code": {"coding": [{"system": ALCOHOL_SYSTEM, "code": ALCOHOL_CODE,
                                 "display": "Alcoholic drinks per day (synthetic)"}]},
            "subject": {"reference": patient.get("fullUrl", f"Patient/{pid}")},
            "effectiveDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "valueQuantity": {"value": sample(rng), "unit": "drinks/day"},
        },
        "request": {"method": "POST", "url": "Observation"},
    })
    path.write_text(json.dumps(b))
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    files = sorted(args.folder.glob("*.json"))
    done = sum(process(f, args.seed) for f in files)
    print(f"Added alcohol observation to {done} of {len(files)} bundles")
