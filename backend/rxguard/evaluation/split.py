"""Drug-disjoint (cold-drug) split for the ML severity predictor (evaluation plan: 20% held out,
split by drug so test drugs are unseen).

Why by drug: the predictor exists for pairs *missing* from DDInter, which in practice involve a
drug the model has seen little of. A random split by pair would put warfarin+X in train and
warfarin+Y in test, so the model could score well just by memorising "warfarin pairs are Major".

Rules:
  * Pairs are de-duplicated on a canonical key first (A-B == B-A, case, whitespace, salt
    suffixes), keeping the most severe level, so the same pair cannot land on both sides.
  * A fraction of drugs is held out. TEST = every pair touching a held-out drug.
    TRAIN/VAL = pairs where both drugs are kept. VAL is carved out the same way from the kept
    drugs, for calibration, threshold tuning and model selection; TEST is touched once.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Iterable

RANK = {"Minor": 1, "Moderate": 2, "Major": 3}

# Stopgap until pairs are keyed by RxNorm ingredient ID: strip common salt/ester words so
# "warfarin sodium" and "warfarin" count as one drug for splitting.
_SALT_WORDS = {
    "sodium", "potassium", "calcium", "magnesium", "hydrochloride", "hcl", "hydrobromide",
    "sulfate", "sulphate", "phosphate", "acetate", "citrate", "maleate", "mesylate",
    "besylate", "tartrate", "succinate", "fumarate", "bromide", "chloride", "monohydrate",
    "dihydrate", "trihydrate", "anhydrous",
}


def canonical_drug(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split()
    kept = [t for t in tokens if t not in _SALT_WORDS]
    return " ".join(kept or tokens)


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    a, b = canonical_drug(a), canonical_drug(b)
    return (a, b) if a <= b else (b, a)


Pair = tuple[str, str, str]  # (drug_a, drug_b, severity) with a <= b, canonical names


def dedupe(rows: Iterable[tuple[str, str, str]]) -> list[Pair]:
    """Canonicalise and de-duplicate, keeping the most severe level. Drops self-pairs."""
    best: dict[tuple[str, str], str] = {}
    for a, b, level in rows:
        if level not in RANK:
            continue
        k = canonical_pair(a, b)
        if k[0] == k[1]:
            continue  # a salt variant paired with itself
        if RANK[level] > RANK.get(best.get(k, ""), 0):
            best[k] = level
    return sorted((a, b, s) for (a, b), s in best.items())


@dataclass
class DrugSplit:
    train: list[Pair]
    val: list[Pair]
    test: list[Pair]
    test_drugs: set[str] = field(default_factory=set)
    val_drugs: set[str] = field(default_factory=set)

    @staticmethod
    def drugs(pairs: Iterable[Pair]) -> set[str]:
        return {d for a, b, _ in pairs for d in (a, b)}


def _hold_out(pairs: list[Pair], frac: float, rng: random.Random) -> tuple[list[Pair], list[Pair], set[str]]:
    drugs = sorted(DrugSplit.drugs(pairs))
    rng.shuffle(drugs)
    held = set(drugs[: max(1, round(frac * len(drugs)))])
    out = [p for p in pairs if p[0] in held or p[1] in held]
    kept = [p for p in pairs if p[0] not in held and p[1] not in held]
    return kept, out, held


def drug_disjoint_split(rows: Iterable[tuple[str, str, str]], test_frac: float = 0.10,
                        val_frac: float = 0.10, seed: int = 0) -> DrugSplit:
    """Hold out drugs, not pairs.

    Because a held-out drug takes all its pairs with it, ~10% of drugs yields roughly 20% of
    pairs (the evaluation plan's target); check len(test)/total and adjust test_frac if needed.
    """
    pairs = dedupe(rows)
    rng = random.Random(seed)
    rest, test, test_drugs = _hold_out(pairs, test_frac, rng)
    train, val, val_drugs = _hold_out(rest, val_frac, rng)
    return DrugSplit(train, val, test, test_drugs, val_drugs)


def cluster_of(pair: Pair, test_drugs: set[str]) -> str:
    """Group ID for the bootstrap: the held-out drug in the pair (first alphabetically if both)."""
    return pair[0] if pair[0] in test_drugs else pair[1]
