"""Offline pipeline 1: load DDInter CSV downloads into the SQLite interaction store.

    python scripts/load_ddinter.py data/raw/ddinter/*.csv

Download the CSVs (one per ATC code group) from the DDInter site under its academic licence.
Pairs are keyed by lowercase ingredient name for now; merging by RxNorm ID is the next step.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.interactions.store import InteractionStore  # noqa: E402

if __name__ == "__main__":
    files = [Path(p) for p in sys.argv[1:]]
    if not files:
        sys.exit("usage: load_ddinter.py CSV [CSV ...]")
    store = InteractionStore(ROOT / "data" / "interactions.sqlite")
    n = store.load_ddinter_csv(files)
    print(f"Loaded {n} unique pairs from {len(files)} file(s); store now has {store.count()} pairs")
