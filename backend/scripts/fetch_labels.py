"""Offline pipeline 3a: download FDA labels from openFDA and split them into passages.

    python scripts/fetch_labels.py                       # every drug in config/drug_flags.yaml
    python scripts/fetch_labels.py --drugs clopidogrel omeprazole
    python scripts/fetch_labels.py --top 150             # + the 150 drugs with most DDInter pairs

Writes data/labels/raw/<drug>.json (the chosen label) and rebuilds data/labels/passages.jsonl
from every raw file. No API key needed (openFDA allows 240 requests/minute without one; set
OPENFDA_API_KEY for more). Then optionally embed the passages:  python scripts/build_label_index.py
Without that step the API uses TF-IDF retrieval over the same passages.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.explain.labels import best_label, passages_from_label, write_passages  # noqa: E402
from rxguard.interactions.store import InteractionStore  # noqa: E402

OPENFDA = "https://api.fda.gov/drug/label.json"


def search(client: httpx.Client, drug: str) -> list[dict]:
    params = {"search": f'openfda.generic_name:"{drug}"', "limit": 25}
    if os.getenv("OPENFDA_API_KEY"):
        params["api_key"] = os.environ["OPENFDA_API_KEY"]
    r = client.get(OPENFDA, params=params)
    if r.status_code == 404:  # openFDA answers 404 when nothing matches
        return []
    r.raise_for_status()
    return r.json().get("results", [])


def top_store_drugs(db: Path, n: int) -> list[str]:
    conn = InteractionStore(db).conn
    rows = conn.execute(
        "SELECT d, COUNT(*) c FROM (SELECT drug_a d FROM interactions UNION ALL SELECT drug_b FROM interactions)"
        " GROUP BY d ORDER BY c DESC LIMIT ?", (n,)).fetchall()
    return [r[0] for r in rows]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drugs", nargs="*", default=[])
    ap.add_argument("--top", type=int, default=0, help="also fetch the N drugs with most DDInter pairs")
    ap.add_argument("--refresh", action="store_true", help="re-download labels already on disk")
    ap.add_argument("--data", default=ROOT / "data")
    args = ap.parse_args(argv)

    data = Path(args.data)
    raw_dir = data / "labels" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    flags = yaml.safe_load((ROOT / "config" / "drug_flags.yaml").read_text())["drugs"]
    drugs = list(dict.fromkeys([*flags, *[d.lower() for d in args.drugs],
                                *(top_store_drugs(data / "interactions.sqlite", args.top) if args.top else [])]))

    with httpx.Client(timeout=30) as client:
        for drug in drugs:
            out = raw_dir / f"{drug.replace('/', '_')}.json"
            if out.exists() and not args.refresh:
                continue
            try:
                label = best_label(search(client, drug), drug)
            except httpx.HTTPError as e:
                print(f"  {drug}: request failed ({e})")
                continue
            if label is None:
                print(f"  {drug}: no label found")
                continue
            label["_rxguard_drug"] = drug
            out.write_text(json.dumps(label))
            print(f"  {drug}: {', '.join(label.get('openfda', {}).get('brand_name', [])[:2]) or 'label'}"
                  f" (set_id {label.get('set_id', '?')[:8]})")
            time.sleep(0.3)

    passages = []
    for f in sorted(raw_dir.glob("*.json")):
        label = json.loads(f.read_text())
        passages += passages_from_label(label, label.get("_rxguard_drug", f.stem))
    n = write_passages(passages, data / "labels" / "passages.jsonl")
    print(f"{n} passages from {len(list(raw_dir.glob('*.json')))} labels -> {data / 'labels' / 'passages.jsonl'}")


if __name__ == "__main__":
    main()
