"""Validation audit Q4: 95% intervals and model-vs-baseline difference from the saved results.

    python scripts/audit_intervals.py                      # Random Forest vs logistic regression
    python scripts/audit_intervals.py --model xgboost

Reads docs/results/model_comparison.json (confusion matrices on the held-out-drug test split,
after the Major guard; columns Major, Moderate, Minor, Unknown) and prints the README results row.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.evaluation.metrics import confusion_bootstrap, results_row  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=ROOT.parent / "docs" / "results" / "model_comparison.json")
    ap.add_argument("--model", default="rf")
    ap.add_argument("--baseline", default="logreg")
    ap.add_argument("--min-gain", type=float, default=0.05)
    args = ap.parse_args()

    d = json.loads(Path(args.results).read_text())
    res = confusion_bootstrap(d[args.model]["confusion"], d[args.baseline]["confusion"])
    print(f"Test pairs: {d['split']['test']}  held-out drugs: {d['split']['test_drugs']}")
    for k in ("model", "baseline", "delta", "model_major_recall", "baseline_major_recall"):
        p, lo, hi = res[k]
        print(f"{k:22s} {p:.3f} [{lo:.3f}, {hi:.3f}]")
    print("\n" + results_row(res))
    print(f"Δ interval excludes 0: {res['delta'][1] > 0}   Δ > {args.min_gain}: {res['delta'][0] > args.min_gain}")
