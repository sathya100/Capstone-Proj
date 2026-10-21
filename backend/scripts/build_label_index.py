"""Offline pipeline 3b: embed the label passages into ChromaDB with all-MiniLM-L6-v2.

    pip install -r requirements-rag.txt
    python scripts/build_label_index.py

Reads data/labels/passages.jsonl (from fetch_labels.py) and writes data/labels/chroma/.
The first run downloads the embedding model (~90 MB) from Hugging Face; after that it is offline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.explain.labels import read_passages  # noqa: E402
from rxguard.explain.retriever import build_chroma_index  # noqa: E402

if __name__ == "__main__":
    data = ROOT / "data"
    passages = read_passages(data / "labels" / "passages.jsonl")
    if not passages:
        sys.exit("no passages: run scripts/fetch_labels.py first")
    t0 = time.time()
    n = build_chroma_index(passages, data / "labels" / "chroma")
    print(f"Indexed {n} passages in {time.time() - t0:.0f}s -> {data / 'labels' / 'chroma'}")
