"""Metrics, 95% intervals and the paired model-vs-baseline comparison.

Test pairs are not independent: every pair touching a held-out drug shares that drug. So the
bootstrap resamples *drugs* (clusters), not pairs, and the model and baseline are scored on the
same resample each time (paired), which is what makes the interval on the difference valid.
With several runs (seeds), each resample averages the metric over the runs.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

LABELS = ("Minor", "Moderate", "Major")


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str], labels=LABELS) -> float:
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    f1s = []
    for c in labels:
        tp = np.sum((yt == c) & (yp == c))
        fp = np.sum((yt != c) & (yp == c))
        fn = np.sum((yt == c) & (yp != c))
        denom = 2 * tp + fp + fn
        f1s.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(f1s))


def major_recall(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    n = np.sum(yt == "Major")
    return float(np.sum((yt == "Major") & (yp == "Major")) / n) if n else float("nan")


Metric = Callable[[Sequence[str], Sequence[str]], float]


def paired_cluster_bootstrap(y_true: Sequence[str], model_runs: Sequence[Sequence[str]],
                             baseline: Sequence[str], clusters: Sequence[str],
                             metric: Metric = macro_f1, n_boot: int = 2000,
                             seed: int = 0) -> dict:
    """Point estimates and 95% percentile intervals for the model, the baseline and the difference.

    model_runs: one prediction list per run (e.g. 5 seeds), all aligned with y_true.
    clusters:   group ID per row (the held-out drug), resampled with replacement.
    """
    yt = np.asarray(y_true)
    runs = [np.asarray(r) for r in model_runs]
    yb = np.asarray(baseline)
    cl = np.asarray(clusters)
    groups = np.unique(cl)
    idx_by_group = {g: np.flatnonzero(cl == g) for g in groups}
    rng = np.random.default_rng(seed)

    def score(idx):
        m = float(np.mean([metric(yt[idx], r[idx]) for r in runs]))
        b = metric(yt[idx], yb[idx])
        return m, b, m - b

    all_idx = np.arange(len(yt))
    point = score(all_idx)
    boots = np.empty((n_boot, 3))
    for i in range(n_boot):
        pick = rng.choice(groups, size=len(groups), replace=True)
        boots[i] = score(np.concatenate([idx_by_group[g] for g in pick]))
    lo, hi = np.nanpercentile(boots, [2.5, 97.5], axis=0)
    names = ("model", "baseline", "delta")
    out = {n: (point[k], lo[k], hi[k]) for k, n in enumerate(names)}
    out["runs"] = len(runs)
    out["n_clusters"] = len(groups)
    return out


def results_row(res: dict, name: str = "Macro F1") -> str:
    """README row in the course format."""
    m, d = res["model"], res["delta"]
    return (f"{name} = {m[0]:.2f} [{m[1]:.2f}, {m[2]:.2f}] · "
            f"Δ vs. baseline = {d[0]:+.2f} [{d[1]:+.2f}, {d[2]:+.2f}] · {res['runs']} runs")


def beats_baseline(res: dict, min_meaningful_gain: float) -> tuple[bool, bool]:
    """(significant: interval of Δ excludes 0, meaningful: Δ > smallest gain that matters)."""
    _, lo, _ = res["delta"]
    return lo > 0, res["delta"][0] > min_meaningful_gain
