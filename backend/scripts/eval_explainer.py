"""Evaluate retrieval and explanations (evaluation plan: RAG retrieval + Explanation rows).

    python scripts/eval_explainer.py                          # all pairs of drugs with labels
    python scripts/eval_explainer.py --questions eval/retrieval_questions.csv
    python scripts/eval_explainer.py --ragas                  # also run RAGAS faithfulness (optional)

Retrieval Recall@5: for each row of the questions CSV (drug_a, drug_b, expected_drug,
expected_section), is a passage from that drug's label section among the top 5? Target 0.85.

Explanations: for each pair, share of output sentences with a valid citation (must be 100%, NFR-04),
how many generated sentences the citation check dropped (FR-13), how often nothing supported
could be said, and latency (NFR-01). Also writes data/eval/explanations.jsonl in the
question/answer/contexts format RAGAS expects, so faithfulness can be scored (target 0.90).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rxguard.explain.explainer import build_explainer  # noqa: E402


def recall_at_k(explainer, rows: list[dict], k: int = 5) -> dict:
    hits = []
    for r in rows:
        got = explainer.retriever.retrieve(r["drug_a"], r["drug_b"], k=k, min_per_drug=min(2, k // 2))[:k]
        want_drug, want_sec = r["expected_drug"].lower(), r["expected_section"].strip().lower()
        hits.append(any(p.drug == want_drug and (want_sec in (p.section, p.section_title.lower())) for p in got))
    return {"n": len(rows), f"recall@{k}": round(sum(hits) / len(hits), 4) if hits else None}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", help="CSV: drug_a,drug_b,expected_drug,expected_section")
    ap.add_argument("--pairs", help="CSV: drug_a,drug_b (default: all pairs of indexed drugs, max 100)")
    ap.add_argument("--ragas", action="store_true")
    args = ap.parse_args(argv)

    data = ROOT / "data"
    explainer = build_explainer(data)
    report: dict = {"retriever": explainer.retriever.name,
                    "provider": explainer.llm.name if explainer.llm else "extractive"}

    if args.questions:
        rows = list(csv.DictReader(open(args.questions, newline="")))
        report["retrieval"] = recall_at_k(explainer, rows)

    if args.pairs:
        pairs = [(r["drug_a"], r["drug_b"]) for r in csv.DictReader(open(args.pairs, newline=""))]
    else:
        pairs = list(combinations(sorted(explainer.retriever.drugs()), 2))[:100]

    out_rows, latencies, cited, total, dropped, empty = [], [], 0, 0, 0, 0
    for a, b in pairs:
        res = explainer.explain(a, b)
        ex = res["explanation"]
        latencies.append(ex["latency_ms"])
        total += len(ex["sentences"])
        cited += sum(1 for s in ex["sentences"] if s["sources"])
        dropped += len(ex["dropped"])
        empty += ex["status"] != "ok"
        out_rows.append({"question": f"How do {a} and {b} interact, and what should be monitored?",
                         "answer": " ".join(s["text"] for s in ex["sentences"]),
                         "contexts": [s["text"] for s in ex["sources"]] or [r["citation"] for r in ex["retrieved"]],
                         "pair": [a, b], "status": ex["status"]})

    report["explanations"] = {
        "pairs": len(pairs),
        "sentences": total,
        "sentences_with_valid_citation": round(cited / total, 4) if total else None,
        "dropped_by_citation_check": dropped,
        "no_supported_explanation": empty,
        "latency_ms_median": statistics.median(latencies) if latencies else None,
        "latency_ms_p95": sorted(latencies)[int(0.95 * (len(latencies) - 1))] if latencies else None,
    }

    out_dir = data / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "explanations.jsonl", "w") as f:
        for r in out_rows:
            f.write(json.dumps(r) + "\n")

    if args.ragas:
        try:
            from datasets import Dataset
            from ragas import evaluate
            from ragas.metrics import faithfulness
            ds = Dataset.from_list([r for r in out_rows if r["answer"]])
            report["ragas_faithfulness"] = float(evaluate(ds, metrics=[faithfulness])["faithfulness"])
        except Exception as e:  # RAGAS needs its own LLM configuration (see the RAGAS docs)
            report["ragas_faithfulness"] = f"not run: {e}"

    (out_dir / "explainer_metrics.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
