"""Create development fixtures: the two worked-example patients from the spec and a seed
interaction row, so the API runs before DDInter and Synthea are set up.

    python scripts/make_dev_data.py

The seed interaction is the spec's own example (acetaminophen + warfarin = Moderate) and is
replaced when you load real DDInter data with scripts/load_ddinter.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.interactions.store import InteractionStore  # noqa: E402
from rxguard.patients.fhir import ALCOHOL_CODE, ALCOHOL_SYSTEM  # noqa: E402


def obs(code: str, system: str, value: float, unit: str, when: str) -> dict:
    return {"resource": {"resourceType": "Observation", "status": "final",
                         "code": {"coding": [{"system": system, "code": code}]},
                         "valueQuantity": {"value": value, "unit": unit},
                         "effectiveDateTime": when}}


def condition(display: str) -> dict:
    return {"resource": {"resourceType": "Condition",
                         "clinicalStatus": {"coding": [{"code": "active"}]},
                         "code": {"coding": [{"display": display}], "text": display}}}


def bundle(pid: str, birth: str, entries: list[dict]) -> dict:
    return {"resourceType": "Bundle", "type": "searchset",
            "entry": [{"resource": {"resourceType": "Patient", "id": pid, "birthDate": birth}}] + entries}


LOINC = "http://loinc.org"
PATIENTS = {
    # Spec example: age 68, chronic liver disease, 4 drinks/day -> acetaminophen+warfarin scores 9 (High)
    "P-1042": bundle("P-1042", "1958-03-14", [
        condition("Chronic liver disease"),
        obs("33914-3", LOINC, 72, "mL/min/1.73m2", "2026-08-01T09:00:00Z"),
        obs("1742-6", LOINC, 55, "U/L", "2026-08-01T09:00:00Z"),
        obs(ALCOHOL_CODE, ALCOHOL_SYSTEM, 4, "drinks/day", "2026-08-01T09:00:00Z"),
    ]),
    # Spec example: age 30, no conditions, no alcohol -> same pair scores 4 (Moderate)
    "P-2210": bundle("P-2210", "1996-05-02", [
        obs("33914-3", LOINC, 105, "mL/min/1.73m2", "2026-07-10T09:00:00Z"),
        obs("1742-6", LOINC, 22, "U/L", "2026-07-10T09:00:00Z"),
        obs(ALCOHOL_CODE, ALCOHOL_SYSTEM, 0, "drinks/day", "2026-07-10T09:00:00Z"),
    ]),
}


def main(data_dir: Path = ROOT / "data") -> None:
    pdir = data_dir / "patients"
    pdir.mkdir(parents=True, exist_ok=True)
    for pid, b in PATIENTS.items():
        (pdir / f"{pid}.json").write_text(json.dumps(b, indent=1))
    store = InteractionStore(data_dir / "interactions.sqlite")
    store.conn.execute("INSERT OR REPLACE INTO interactions VALUES ('acetaminophen', 'warfarin', 'Moderate')")
    store.conn.commit()
    print(f"Wrote {len(PATIENTS)} patients to {pdir} and seed interaction ({store.count()} pairs in store)")


if __name__ == "__main__":
    main()
