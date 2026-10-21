"""Offline pipeline 2b: train the severity classifier on DDInter pairs and evaluate it.

    python scripts/fetch_smiles.py                   # once: data/smiles.json from PubChem
    python scripts/train_predictor.py                # default model: HistGradientBoosting
    python scripts/train_predictor.py --model xgboost   # needs: pip install xgboost

Reads the DDInter pairs from data/interactions.sqlite and SMILES from data/smiles.json, builds
Morgan fingerprints with RDKit, evaluates on a drug-level split (test drugs unseen in training)
against majority-class and logistic-regression baselines, then writes:

    data/models/severity_model.joblib    loaded by the API automatically (FR-05)
    data/models/severity_metrics.json    numbers for the evaluation table in the report

Memory: about 1 KB per pair, so all ~240k DDInter pairs need ~250 MB. Use --max-pairs to sample.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.interactions.store import InteractionStore  # noqa: E402
from rxguard.ml.features import DEFAULT_BITS, fingerprints_for  # noqa: E402
from rxguard.ml.train import train_and_evaluate  # noqa: E402


def load_pairs(db: Path) -> list[tuple[str, str, str]]:
    store = InteractionStore(db)
    return [tuple(r) for r in store.conn.execute("SELECT drug_a, drug_b, severity FROM interactions")]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=ROOT / "data" / "interactions.sqlite")
    ap.add_argument("--smiles", default=ROOT / "data" / "smiles.json")
    ap.add_argument("--out-dir", default=ROOT / "data" / "models")
    ap.add_argument("--model", default="hgb", choices=["hgb", "xgboost", "rf", "logreg"])
    ap.add_argument("--bits", type=int, default=DEFAULT_BITS)
    ap.add_argument("--target-major-recall", type=float, default=0.90)
    ap.add_argument("--max-pairs", type=int, default=0, help="random sample of pairs (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text())
    min_conf = rules["ml"]["min_confidence"]

    pairs = load_pairs(Path(args.db))
    if args.max_pairs and len(pairs) > args.max_pairs:
        pairs = random.Random(args.seed).sample(pairs, args.max_pairs)
    smiles = json.loads(Path(args.smiles).read_text())
    print(f"{len(pairs)} pairs, {sum(1 for v in smiles.values() if v)} drugs with SMILES")

    t0 = time.time()
    fps = fingerprints_for(smiles, n_bits=args.bits)
    pairs = [p for p in pairs if p[0] in fps and p[1] in fps]
    print(f"{len(fps)} fingerprints; {len(pairs)} pairs where both drugs have one ({time.time()-t0:.0f}s)")

    t0 = time.time()
    bundle, report = train_and_evaluate(pairs, fps, args.model, args.target_major_recall, min_conf, args.seed)
    report["train_seconds"] = round(time.time() - t0)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(bundle, out / "severity_model.joblib", compress=3)
    (out / "severity_metrics.json").write_text(json.dumps(report, indent=2))

    t, b = report["test"], report["baselines"]
    print(f"\nTest (unseen drugs, n={t['n']}):  macro F1 {t['macro_f1']}  Major recall {t.get('major_recall')}"
          f"  Major shown safely {t.get('major_safe_recall')}  coverage {t.get('coverage')}")
    for name, m in b.items():
        print(f"  baseline {name:20s} macro F1 {m['macro_f1']}  Major recall {m.get('major_recall')}")
    print(f"Targets met: {report['meets_targets']}")
    print(f"Saved {out / 'severity_model.joblib'} and severity_metrics.json")


if __name__ == "__main__":
    main()
