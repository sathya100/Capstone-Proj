"""Step 2: base severity from DDInter (FR-04), falling back to the ML predictor (FR-05, NFR-03).

Offline pipeline 1 loads DDInter CSVs into SQLite with scripts/load_ddinter.py.
DDInter CSV columns: DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable, Optional, Protocol

from rxguard.models import SeverityResult

VALID_LEVELS = {"Major", "Moderate", "Minor"}


def _key(a: str, b: str) -> tuple[str, str]:
    a, b = a.strip().lower(), b.strip().lower()
    return (a, b) if a <= b else (b, a)


class InteractionStore:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS interactions ("
            " drug_a TEXT NOT NULL, drug_b TEXT NOT NULL, severity TEXT NOT NULL,"
            " PRIMARY KEY (drug_a, drug_b))"
        )

    def load_ddinter_csv(self, paths: Iterable[Path | str]) -> int:
        """Load one or more DDInter CSVs. Keeps the most severe level if a pair repeats."""
        rank = {"Minor": 1, "Moderate": 2, "Major": 3}
        best: dict[tuple[str, str], str] = {}
        for p in paths:
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    level = (row.get("Level") or "").strip()
                    if level not in VALID_LEVELS:
                        continue  # DDInter "Unknown" rows are not ground truth
                    k = _key(row["Drug_A"], row["Drug_B"])
                    if rank[level] > rank.get(best.get(k, ""), 0):
                        best[k] = level
        self.conn.executemany(
            "INSERT OR REPLACE INTO interactions VALUES (?, ?, ?)",
            [(a, b, s) for (a, b), s in best.items()],
        )
        self.conn.commit()
        return len(best)

    def lookup(self, a: str, b: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT severity FROM interactions WHERE drug_a=? AND drug_b=?", _key(a, b)
        ).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]


class SeverityPredictor(Protocol):
    def predict(self, a: str, b: str) -> tuple[Optional[str], float]:
        """Return (severity label or None, confidence)."""


class NoModelPredictor:
    """Placeholder until the week 3–4 classifier exists: always unknown."""

    def predict(self, a: str, b: str) -> tuple[Optional[str], float]:
        return None, 0.0


def base_severity(store: InteractionStore, predictor: SeverityPredictor,
                  a: str, b: str, min_confidence: float) -> SeverityResult:
    found = store.lookup(a, b)
    if found:
        return SeverityResult(found, "DDInter")
    label, conf = predictor.predict(a, b)
    if label is None or conf < min_confidence:
        return SeverityResult(None, "unknown", conf if label else None)
    return SeverityResult(label, "predicted", conf)
