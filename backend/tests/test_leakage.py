"""Leakage tests for the ML severity predictor's train / val / test split (validation audit Q3).

Run on a synthetic DDInter-like table so they pass in CI without the licensed data, and on the
real DDInter CSVs when they are present in data/raw/ddinter/.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from rxguard.evaluation.metrics import major_recall, macro_f1, paired_cluster_bootstrap, results_row
from rxguard.evaluation.split import (DrugSplit, canonical_pair, cluster_of, dedupe,
                                      drug_disjoint_split)

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "ddinter"


def synthetic_rows(n_drugs=120, n_pairs=2500, seed=1):
    rng = random.Random(seed)
    drugs = [f"drug{i}" for i in range(n_drugs)]
    rows = []
    for _ in range(n_pairs):
        a, b = rng.sample(drugs, 2)
        rows.append((a, b, rng.choice(["Minor", "Moderate", "Major"])))
    # duplicates DDInter actually contains: reversed order, case, salt form, repeated across files
    rows += [("Drug3", "drug7", "Minor"), ("drug7 sodium", "DRUG3", "Major"),
             ("drug3", "drug7", "Moderate"), ("drug9 hydrochloride", "drug9", "Major")]
    return rows


def ddinter_rows():
    import csv
    for p in sorted(RAW.glob("*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                yield r["Drug_A"], r["Drug_B"], (r.get("Level") or "").strip()


SOURCES = [pytest.param(synthetic_rows, id="synthetic"),
           pytest.param(ddinter_rows, id="ddinter",
                        marks=pytest.mark.skipif(not any(RAW.glob("*.csv")),
                                                 reason="DDInter CSVs not downloaded"))]


@pytest.fixture(params=SOURCES)
def split(request):
    return drug_disjoint_split(request.param(), seed=0)


def keys(pairs):
    return {(a, b) for a, b, _ in pairs}


def test_no_drug_shared_between_train_and_test(split):
    assert DrugSplit.drugs(split.train).isdisjoint(split.test_drugs)
    assert DrugSplit.drugs(split.val).isdisjoint(split.test_drugs)


def test_no_drug_shared_between_train_and_val(split):
    assert DrugSplit.drugs(split.train).isdisjoint(split.val_drugs)


def test_every_test_pair_has_an_unseen_drug(split):
    seen = DrugSplit.drugs(split.train) | DrugSplit.drugs(split.val)
    assert all(a not in seen or b not in seen for a, b, _ in split.test)


def test_no_pair_in_two_sets_in_either_order(split):
    tr, va, te = keys(split.train), keys(split.val), keys(split.test)
    assert tr.isdisjoint(te) and tr.isdisjoint(va) and va.isdisjoint(te)
    flipped = {(b, a) for a, b in tr}
    assert flipped.isdisjoint(te)


def test_split_covers_every_pair_once(split):
    total = len(split.train) + len(split.val) + len(split.test)
    assert len(keys(split.train) | keys(split.val) | keys(split.test)) == total


def test_test_set_is_roughly_a_fifth_of_pairs(split):
    total = len(split.train) + len(split.val) + len(split.test)
    assert 0.12 <= len(split.test) / total <= 0.35


def test_split_is_reproducible():
    a, b = drug_disjoint_split(synthetic_rows(), seed=3), drug_disjoint_split(synthetic_rows(), seed=3)
    assert a.test == b.test and a.train == b.train


def test_dedupe_merges_order_case_and_salt_keeping_most_severe():
    pairs = dedupe(synthetic_rows())
    match = [p for p in pairs if (p[0], p[1]) == canonical_pair("drug3", "drug7")]
    assert match == [("drug3", "drug7", "Major")]
    assert all(a != b for a, b, _ in pairs)  # salt-vs-parent self pair dropped


# --- interval code (Handout 2 style, resampling by held-out drug) -------------------------------

def test_paired_bootstrap_detects_a_real_gap_and_not_a_null_one():
    split = drug_disjoint_split(synthetic_rows(n_pairs=4000), seed=0)
    y = [s for _, _, s in split.test]
    cl = [cluster_of(p, split.test_drugs) for p in split.test]
    rng = np.random.default_rng(0)

    def noisy(acc):
        return [t if rng.random() < acc else rng.choice(["Minor", "Moderate", "Major"]) for t in y]

    base = noisy(0.5)
    better = paired_cluster_bootstrap(y, [noisy(0.8) for _ in range(5)], base, cl, n_boot=300)
    assert better["delta"][1] > 0                      # interval excludes 0
    same = paired_cluster_bootstrap(y, [noisy(0.5) for _ in range(5)], base, cl, n_boot=300)
    assert same["delta"][1] < 0 < same["delta"][2]     # interval contains 0
    assert "· 5 runs" in results_row(better)


def test_metrics_basic():
    assert macro_f1(["Major", "Minor"], ["Major", "Minor"]) == pytest.approx(2 / 3)  # Moderate absent
    assert major_recall(["Major", "Major", "Minor"], ["Major", "Minor", "Minor"]) == 0.5
