"""Leakage tests for the severity predictor's train / val / test split (validation audit Q3).

They test the code that produced the reported results: the DDInter loader's de-duplication
(rxguard/interactions/store.py) and the drug-level split (rxguard/ml/train.py::drug_split).
They run on a synthetic DDInter-shaped table in CI, and also on the real store when
data/interactions.sqlite holds loaded DDInter pairs.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

import numpy as np
import pytest

from rxguard.evaluation.metrics import (confusion_bootstrap, major_recall, macro_f1,
                                        paired_cluster_bootstrap, results_row)
from rxguard.interactions.store import InteractionStore
from rxguard.ml.train import drug_split

DB = Path(__file__).resolve().parents[1] / "data" / "interactions.sqlite"
LEVELS = ["Minor", "Moderate", "Major"]


def write_ddinter_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"])
        for i, (a, b, lvl) in enumerate(rows):
            w.writerow([f"DDInter{i}", a, f"DDInter{i}b", b, lvl])


def synthetic_pairs(tmp_path, n_drugs=150, n_pairs=3000, seed=1):
    """Load synthetic rows through the real DDInter loader, including the duplicates DDInter has:
    reversed order, different case/whitespace, and the same pair in two per-ATC files."""
    rng = random.Random(seed)
    drugs = [f"drug{i}" for i in range(n_drugs)]
    rows = [(*rng.sample(drugs, 2), rng.choice(LEVELS)) for _ in range(n_pairs)]
    dupes = [(b.upper(), f" {a} ", lvl) for a, b, lvl in rows[:200]]
    write_ddinter_csv(tmp_path / "code_A.csv", rows)
    write_ddinter_csv(tmp_path / "code_B.csv", dupes + [("Drug1", "drug2", "Unknown")])
    store = InteractionStore(tmp_path / "x.sqlite")
    store.load_ddinter_csv([tmp_path / "code_A.csv", tmp_path / "code_B.csv"])
    return [tuple(r) for r in store.conn.execute("SELECT drug_a, drug_b, severity FROM interactions")]


def real_pairs(_tmp_path):
    store = InteractionStore(DB)
    return [tuple(r) for r in store.conn.execute("SELECT drug_a, drug_b, severity FROM interactions")]


def _real_store_loaded() -> bool:
    try:
        return DB.exists() and InteractionStore(DB).count() > 1000
    except Exception:
        return False


SOURCES = [pytest.param(synthetic_pairs, id="synthetic"),
           pytest.param(real_pairs, id="ddinter",
                        marks=pytest.mark.skipif(not _real_store_loaded(), reason="DDInter not loaded"))]


@pytest.fixture(params=SOURCES)
def pairs(request, tmp_path):
    return request.param(tmp_path)


@pytest.fixture
def split(pairs):
    return drug_split(pairs, seed=42)  # same seed as scripts/train_predictor.py


def drugs(ps):
    return {d for a, b, _ in ps for d in (a, b)}


def keys(ps):
    return {frozenset((a, b)) for a, b, _ in ps}


def test_loader_stores_each_pair_once_in_either_order(pairs):
    assert len(keys(pairs)) == len(pairs)


def test_train_and_test_share_no_drug_ids(split):
    assert drugs(split.train).isdisjoint(split.test_drugs)
    assert drugs(split.val).isdisjoint(split.test_drugs)


def test_train_and_val_share_no_validation_drug(split):
    assert drugs(split.train).isdisjoint(split.val_drugs)


def test_every_test_pair_has_a_drug_unseen_in_training(split):
    seen = drugs(split.train) | drugs(split.val)
    assert all(a not in seen or b not in seen for a, b, _ in split.test)


def test_no_pair_appears_in_two_sets(split):
    tr, va, te = keys(split.train), keys(split.val), keys(split.test)
    assert tr.isdisjoint(te) and tr.isdisjoint(va) and va.isdisjoint(te)


def test_split_covers_every_pair_exactly_once(pairs, split):
    assert len(split.train) + len(split.val) + len(split.test) == len(pairs)


def test_split_is_reproducible(pairs):
    assert drug_split(pairs, seed=42).test == drug_split(pairs, seed=42).test


# --- interval code (validation audit Q4) ----------------------------------------------------------

def test_paired_cluster_bootstrap_detects_a_real_gap_and_not_a_null_one(tmp_path):
    split = drug_split(synthetic_pairs(tmp_path, n_pairs=4000), seed=0)
    y = [s for _, _, s in split.test]
    cl = [a if a in split.test_drugs else b for a, b, _ in split.test]
    rng = np.random.default_rng(0)

    def noisy(acc):
        return [t if rng.random() < acc else rng.choice(LEVELS) for t in y]

    base = noisy(0.5)
    better = paired_cluster_bootstrap(y, [noisy(0.8) for _ in range(5)], base, cl, n_boot=300)
    assert better["delta"][1] > 0                      # interval excludes 0
    same = paired_cluster_bootstrap(y, [noisy(0.5) for _ in range(5)], base, cl, n_boot=300)
    assert same["delta"][1] < 0 < same["delta"][2]     # interval contains 0
    assert results_row(better).endswith("· 5 runs")


def test_confusion_bootstrap_matches_point_metrics():
    cm = [[897, 225, 2, 478], [384, 2442, 7, 967], [15, 34, 55, 18]]  # RF, docs/results
    res = confusion_bootstrap(cm, cm, n_boot=200)
    assert res["model"][0] == pytest.approx(0.6539, abs=1e-4)
    assert res["model_major_recall"][0] == pytest.approx(0.5599, abs=1e-4)
    assert res["model"][1] < res["model"][0] < res["model"][2]
    assert results_row(res).endswith("· 1 run")


def test_metrics_basic():
    assert macro_f1(["Major", "Minor"], ["Major", "Minor"]) == pytest.approx(2 / 3)  # Moderate absent
    assert major_recall(["Major", "Major", "Minor"], ["Major", "Minor", "Minor"]) == 0.5
