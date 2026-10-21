"""Offline pipeline 2a: fetch a SMILES string from PubChem for every drug in the interaction store.

    python scripts/fetch_smiles.py                 # all drugs in data/interactions.sqlite
    python scripts/fetch_smiles.py --drugs warfarin acetaminophen

Writes data/smiles.json ({drug: smiles or null}). Re-running only fetches drugs not yet in the
file, so it can be stopped and resumed. PubChem asks for at most 5 requests per second.
Biologics and mixtures (insulin, vaccines, antibodies) have no SMILES; they are stored as null and
the predictor cannot cover them, so pairs involving them stay "Unknown — consult a pharmacist".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.interactions.store import InteractionStore  # noqa: E402

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/property/IsomericSMILES/JSON"


def fetch_one(client: httpx.Client, name: str) -> str | None:
    r = client.get(PUG.format(quote(name)))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    props = r.json()["PropertyTable"]["Properties"][0]
    # PubChem renamed IsomericSMILES -> SMILES in 2025; accept either key
    for key in ("SMILES", "IsomericSMILES", "CanonicalSMILES", "ConnectivitySMILES"):
        if props.get(key):
            return props[key]
    return None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=ROOT / "data" / "interactions.sqlite")
    ap.add_argument("--out", default=ROOT / "data" / "smiles.json")
    ap.add_argument("--drugs", nargs="*", help="only these drugs (default: every drug in the store)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    smiles: dict[str, str | None] = json.loads(out.read_text()) if out.exists() else {}
    drugs = args.drugs or InteractionStore(args.db).drug_names("", 10**6)
    todo = [d.lower() for d in drugs if d.lower() not in smiles]
    print(f"{len(drugs)} drugs, {len(todo)} to fetch")

    with httpx.Client(timeout=20) as client:
        for i, name in enumerate(todo, 1):
            for attempt in range(3):
                try:
                    smiles[name] = fetch_one(client, name)
                    break
                except (httpx.HTTPError, KeyError, ValueError) as e:
                    if attempt == 2:
                        print(f"  failed: {name}: {e}")
                    time.sleep(2 ** attempt)
            time.sleep(0.22)  # stay under 5 requests/second
            if i % 50 == 0 or i == len(todo):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(smiles, indent=0, sort_keys=True))
                print(f"  {i}/{len(todo)}")

    found = sum(1 for v in smiles.values() if v)
    print(f"SMILES found for {found}/{len(smiles)} drugs -> {out}")


if __name__ == "__main__":
    main()
