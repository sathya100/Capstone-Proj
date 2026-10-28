"""Severity predictor (FR-05, NFR-02, NFR-03): split, guard, training, runtime predictor, pipeline hook.

Uses random synthetic fingerprints so no PubChem/RDKit data is needed; one test checks real
RDKit fingerprints when RDKit is installed.
"""
import itertools
import random
from datetime import date

import numpy as np
import pytest

from rxguard.interactions.store import InteractionStore, base_severity
from rxguard.ml.features import pair_features
from rxguard.ml.predictor import MLPredictor
from rxguard.ml.train import decide, drug_split, evaluate, train_and_evaluate, tune_major_guard


@pytest.fixture(scope="module")
def synthetic():
    rng = np.random.default_rng(0)
    fps = {f"drug{i:03d}": (rng.random(128) < 0.15).astype(np.uint8) for i in range(70)}

    def label(a, b):
        s = int(fps[a][:16].sum() + fps[b][:16].sum())
        return "Major" if s >= 7 else "Moderate" if s >= 4 else "Minor"

    r = random.Random(0)
    pairs = [(a, b, label(a, b)) for a, b in itertools.combinations(sorted(fps), 2) if r.random() < 0.5]
    return fps, pairs


@pytest.fixture(scope="module")
def trained(synthetic):
    fps, pairs = synthetic
    return train_and_evaluate(pairs, fps, model_kind="logreg")


def test_pair_features_are_symmetric():
    a, b = np.array([1, 0, 1, 0], np.uint8), np.array([1, 1, 0, 0], np.uint8)
    assert (pair_features(a, b) == pair_features(b, a)).all()
    assert pair_features(a, b).tolist() == [2, 1, 1, 0]


def test_drug_split_keeps_test_drugs_unseen(synthetic):
    _, pairs = synthetic
    s = drug_split(pairs)
    train_drugs = {d for a, b, _ in s.train for d in (a, b)}
    assert not train_drugs & s.test_drugs
    assert not train_drugs & s.val_drugs
    assert all(a in s.test_drugs or b in s.test_drugs for a, b, _ in s.test)
    assert len(s.train) + len(s.val) + len(s.test) == len(pairs)


def test_major_guard_turns_doubtful_moderate_into_unknown():
    classes = ["Major", "Minor", "Moderate"]
    proba = np.array([[0.30, 0.05, 0.65],    # Moderate, but P(Major) above guard -> Unknown
                      [0.10, 0.05, 0.85],    # clearly Moderate
                      [0.80, 0.10, 0.10]])   # Major
    labels, conf = decide(proba, classes, major_guard=0.25)
    assert labels.tolist() == ["Unknown", "Moderate", "Major"]
    assert conf.tolist() == [0.65, 0.85, 0.80]


def test_tuned_guard_reaches_target_safe_recall():
    rng = np.random.default_rng(1)
    classes = ["Major", "Minor", "Moderate"]
    proba = rng.dirichlet([1, 1, 1], size=400)
    y = np.array([classes[i] for i in rng.integers(0, 3, 400)], dtype=object)
    g = tune_major_guard(proba, y, classes, target_recall=0.9, min_confidence=0.6)
    labels, conf = decide(proba, classes, g)
    assert evaluate(y, labels, conf, 0.6)["major_safe_recall"] >= 0.9


def test_training_report_has_spec_metrics_and_baselines(trained):
    _, report = trained
    t = report["test"]
    for k in ("macro_f1", "major_recall", "major_safe_recall", "coverage", "per_class"):
        assert k in t
    assert set(report["baselines"]) == {"majority_class"}  # logreg is the model here
    assert report["baselines"]["majority_class"]["major_recall"] in (0.0, 1.0)
    assert report["split"]["rule"].startswith("test pairs contain")


def test_hgb_model_compares_against_logistic_baseline(synthetic):
    fps, pairs = synthetic
    _, report = train_and_evaluate(pairs[:600], fps, model_kind="hgb")
    assert set(report["baselines"]) == {"majority_class", "logistic_regression"}


def test_predictor_round_trip_symmetric_and_unknown_drugs(trained, tmp_path):
    bundle, _ = trained
    p = MLPredictor(bundle)
    assert p.predict("drug001", "drug002") == p.predict("drug002", "drug001")
    label, conf = p.predict("drug001", "drug002")
    assert label in (None, "Major", "Moderate", "Minor") and 0 <= conf <= 1
    assert p.predict("drug001", "not-a-drug") == (None, 0.0)
    p.save(tmp_path / "m.joblib")
    assert MLPredictor.load(tmp_path / "m.joblib").predict("drug001", "drug002") == (label, conf)


def test_base_severity_uses_predictor_only_for_missing_pairs(trained, tmp_path):
    store = InteractionStore(tmp_path / "s.sqlite")
    store.conn.execute("INSERT INTO interactions VALUES ('drug001', 'drug002', 'Minor')")
    p = MLPredictor(trained[0])
    assert base_severity(store, p, "drug001", "drug002", 0.6).source == "DDInter"
    sev = base_severity(store, p, "drug003", "drug004", 0.6)
    assert sev.source in ("predicted", "unknown")
    if sev.source == "predicted":
        assert sev.confidence >= 0.6
    else:
        assert sev.severity is None  # never Low (NFR-03)


def test_pipeline_reports_predicted_severity(tmp_path):
    from scripts.make_dev_data import main as make_dev_data
    from rxguard.normalise.rxnorm import RxNormNormaliser
    from rxguard.patients.fhir import FilePatientSource
    from rxguard.pipeline import Pipeline
    from rxguard.rules.engine import RulesEngine

    class Confident:
        def predict(self, a, b):
            return "Major", 0.91

    make_dev_data(tmp_path)
    pipe = Pipeline(RxNormNormaliser(offline=True), InteractionStore(tmp_path / "interactions.sqlite"),
                    FilePatientSource(tmp_path / "patients", today=date(2026, 9, 30)), RulesEngine.from_config(),
                    predictor=Confident())
    out = pipe.check("Advil", "Coumadin", "P-2210", explain=False)
    assert out["severity_source"] == "predicted" and out["base_severity"] == "Major"
    assert out["severity_confidence"] == 0.91
    assert out["score_breakdown"][0]["points"] == 6


def test_rdkit_fingerprint_when_available():
    pytest.importorskip("rdkit")
    from rxguard.ml.features import morgan_fingerprint
    fp = morgan_fingerprint("CC(=O)Nc1ccc(O)cc1", n_bits=512)   # acetaminophen
    assert fp.shape == (512,) and fp.sum() > 0
    assert morgan_fingerprint("not a smiles") is None
