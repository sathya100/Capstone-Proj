"""Training and evaluation for the severity predictor (FR-05, NFR-02, NFR-03).

Evaluation follows the spec: 20% of drugs are held out, so every test pair involves at least one
drug the model never saw. Train pairs use only training drugs. A validation split (also by drug)
is carved from the training drugs to tune the Major guard without touching the test set.

Major guard: when the most likely class is Moderate/Minor but P(Major) >= g, the pair is shown as
"Unknown — consult a pharmacist" instead. g is the largest value that keeps at least the target
share (default 0.90) of true Majors out of Moderate/Minor on validation. A missed Major is the
worst error (NFR-02), so we give up coverage rather than show a Major as something milder.

Reported metrics (test set):
  macro_f1, per-class precision/recall/F1, major_recall,
  major_safe_recall  — share of true Majors that are NOT shown to the user as Moderate/Minor,
                       i.e. predicted Major, or below the confidence floor and shown as Unknown,
  coverage           — share of test pairs that get a confident prediction (>= min_confidence),
  baselines          — majority class and logistic regression on the same split and features.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import numpy as np

from rxguard.ml.features import pair_features

CLASSES = ["Major", "Moderate", "Minor"]


@dataclass
class Split:
    train: list[tuple[str, str, str]]
    val: list[tuple[str, str, str]]
    test: list[tuple[str, str, str]]
    test_drugs: set[str] = field(default_factory=set)
    val_drugs: set[str] = field(default_factory=set)


def drug_split(pairs: Iterable[tuple[str, str, str]], test_frac: float = 0.2, val_frac: float = 0.1,
               seed: int = 42) -> Split:
    """Split (drug_a, drug_b, label) pairs by drug.

    test  = pairs with at least one held-out test drug
    val   = remaining pairs with at least one validation drug
    train = pairs whose two drugs are both training drugs
    """
    pairs = list(pairs)
    drugs = sorted({d for a, b, _ in pairs for d in (a, b)})
    rng = random.Random(seed)
    rng.shuffle(drugs)
    n_test = max(1, int(len(drugs) * test_frac))
    n_val = max(1, int(len(drugs) * val_frac))
    test_drugs = set(drugs[:n_test])
    val_drugs = set(drugs[n_test:n_test + n_val])
    s = Split([], [], [], test_drugs, val_drugs)
    for p in pairs:
        a, b, _ = p
        if a in test_drugs or b in test_drugs:
            s.test.append(p)
        elif a in val_drugs or b in val_drugs:
            s.val.append(p)
        else:
            s.train.append(p)
    return s


def build_matrix(pairs: list[tuple[str, str, str]], fps: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Feature matrix and label vector; pairs with a drug lacking a fingerprint are skipped."""
    rows, labels = [], []
    for a, b, label in pairs:
        fa, fb = fps.get(a), fps.get(b)
        if fa is None or fb is None or label not in CLASSES:
            continue
        rows.append(pair_features(fa, fb))
        labels.append(label)
    if not rows:
        return np.zeros((0, 0), dtype=np.uint8), np.array([], dtype=object)
    return np.vstack(rows), np.array(labels, dtype=object)


def make_model(kind: str = "hgb", seed: int = 42):
    """hgb: sklearn HistGradientBoosting (default, no extra install); xgboost; rf; logreg."""
    if kind == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, class_weight="balanced",
                                              early_stopping=True, random_state=seed)
    if kind == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(n_estimators=300, n_jobs=-1, class_weight="balanced_subsample",
                                      min_samples_leaf=2, random_state=seed)
    if kind == "logreg":
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(max_iter=2000, class_weight="balanced")
    if kind == "xgboost":
        from xgboost import XGBClassifier  # pip install xgboost
        return _LabelEncodedXGB(XGBClassifier(n_estimators=400, max_depth=8, learning_rate=0.1,
                                              subsample=0.8, colsample_bytree=0.5, n_jobs=-1,
                                              random_state=seed, eval_metric="mlogloss"))
    raise ValueError(f"unknown model kind: {kind}")


class _LabelEncodedXGB:
    """XGBoost needs integer labels; this keeps the sklearn string-label interface."""

    def __init__(self, model):
        self.model = model

    def fit(self, X, y):
        self.classes_ = np.array(sorted(set(y)), dtype=object)
        index = {c: i for i, c in enumerate(self.classes_)}
        counts = {c: (y == c).sum() for c in self.classes_}
        weights = np.array([len(y) / (len(counts) * counts[c]) for c in y])  # balanced
        self.model.fit(X, np.array([index[c] for c in y]), sample_weight=weights)
        return self

    def predict_proba(self, X):
        return self.model.predict_proba(X)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(1)]


def decide(proba: np.ndarray, classes: list[str], major_guard: Optional[float]) -> tuple[np.ndarray, np.ndarray]:
    """Labels and confidences from class probabilities.

    The label is the most likely class and the confidence its probability. Major guard: if the most
    likely class is Moderate or Minor but P(Major) >= major_guard, the model cannot rule out a Major
    interaction, so the label becomes "Unknown" and the user sees "Unknown — consult a pharmacist".
    """
    classes = list(classes)
    idx = proba.argmax(1)
    labels = np.array([classes[i] for i in idx], dtype=object)
    conf = proba.max(1).copy()
    if major_guard is not None and "Major" in classes:
        m = classes.index("Major")
        hit = (labels != "Major") & (proba[:, m] >= major_guard)
        labels[hit] = "Unknown"
    return labels, conf


def tune_major_guard(proba: np.ndarray, y: np.ndarray, classes: list[str], target_recall: float = 0.9,
                     min_confidence: float = 0.6) -> Optional[float]:
    """Largest guard on P(Major) such that, on (proba, y), at least target_recall of true Majors are
    shown safely: predicted Major, below the confidence floor, or caught by the guard.
    Returns None when no guard is needed."""
    classes = list(classes)
    if "Major" not in classes or not (y == "Major").any():
        return None
    labels, conf = decide(proba, classes, None)
    major = y == "Major"
    safe = (labels == "Major") | (conf < min_confidence)
    needed = int(np.ceil(target_recall * major.sum())) - int(safe[major].sum())
    if needed <= 0:
        return None
    p_unsafe = np.sort(proba[major & ~safe, classes.index("Major")])[::-1]
    return float(p_unsafe[min(needed, len(p_unsafe)) - 1])


def evaluate(y_true: np.ndarray, labels: np.ndarray, conf: Optional[np.ndarray] = None,
             min_confidence: float = 0.6) -> dict[str, Any]:
    from sklearn.metrics import f1_score, precision_recall_fscore_support

    present = [c for c in CLASSES if c in set(y_true) | set(labels)]
    p, r, f, n = precision_recall_fscore_support(y_true, labels, labels=present, zero_division=0)
    out: dict[str, Any] = {
        "n": int(len(y_true)),
        "macro_f1": round(float(f1_score(y_true, labels, labels=present, average="macro", zero_division=0)), 4),
        "per_class": {c: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                          "f1": round(float(f[i]), 4), "support": int(n[i])} for i, c in enumerate(present)},
    }
    is_major = y_true == "Major"
    if is_major.any():
        out["major_recall"] = round(float((labels[is_major] == "Major").mean()), 4)
        if conf is not None:
            # Major, or shown as "Unknown — consult a pharmacist" (guard or low confidence); never Moderate/Minor
            shown_safe = (labels == "Major") | (labels == "Unknown") | (conf < min_confidence)
            out["major_safe_recall"] = round(float(shown_safe[is_major].mean()), 4)
    if conf is not None:
        out["coverage"] = round(float(((labels != "Unknown") & (conf >= min_confidence)).mean()), 4)
    return out


def train_and_evaluate(pairs: list[tuple[str, str, str]], fps: dict[str, np.ndarray], model_kind: str = "hgb",
                       target_major_recall: float = 0.9, min_confidence: float = 0.6, seed: int = 42,
                       final_fit_on_all: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    """Train, tune and evaluate. Returns (bundle for MLPredictor, metrics report).

    With final_fit_on_all the shipped model is refit on every pair (train + val + test) using the
    tuned guard; reported metrics always come from the held-out drug split.
    """
    from sklearn.dummy import DummyClassifier

    split = drug_split(pairs, seed=seed)
    Xtr, ytr = build_matrix(split.train, fps)
    Xva, yva = build_matrix(split.val, fps)
    Xte, yte = build_matrix(split.test, fps)
    if len(ytr) == 0 or len(yte) == 0:
        raise ValueError("not enough pairs with fingerprints to train and test")

    model = make_model(model_kind, seed).fit(Xtr, ytr)
    classes = list(model.classes_)
    guard = None
    if len(yva):
        guard = tune_major_guard(model.predict_proba(Xva), yva, classes, target_major_recall, min_confidence)

    labels, conf = decide(model.predict_proba(Xte), classes, guard)
    report: dict[str, Any] = {
        "model": model_kind,
        "split": {"train_pairs": int(len(ytr)), "val_pairs": int(len(yva)), "test_pairs": int(len(yte)),
                  "test_drugs": len(split.test_drugs), "val_drugs": len(split.val_drugs),
                  "rule": "test pairs contain at least one drug unseen in training"},
        "major_guard": guard,
        "min_confidence": min_confidence,
        "test": evaluate(yte, labels, conf, min_confidence),
        "test_no_guard": evaluate(yte, *decide(model.predict_proba(Xte), classes, None), min_confidence),
        "baselines": {},
    }
    dummy = DummyClassifier(strategy="most_frequent").fit(Xtr, ytr)
    report["baselines"]["majority_class"] = evaluate(yte, dummy.predict(Xte))
    if model_kind != "logreg":
        lr = make_model("logreg", seed).fit(Xtr, ytr)
        report["baselines"]["logistic_regression"] = evaluate(yte, lr.predict(Xte))

    targets = {"macro_f1": 0.70, "major_recall": target_major_recall, "major_safe_recall": target_major_recall}
    report["targets"] = targets
    report["meets_targets"] = {k: report["test"].get(k, 0) >= v for k, v in targets.items()}

    if final_fit_on_all:
        Xall, yall = build_matrix(split.train + split.val + split.test, fps)
        model = make_model(model_kind, seed).fit(Xall, yall)
        classes = list(model.classes_)

    used = {d for a, b, _ in pairs for d in (a, b)} & set(fps)
    bundle = {
        "model": model,
        "classes": classes,
        "major_guard": guard,
        "fingerprints": {d: np.packbits(fps[d]) for d in sorted(used)},
        "n_bits": int(next(iter(fps.values())).shape[0]),
        "metrics": report,
        "version": 1,
    }
    return bundle, report
