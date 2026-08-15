"""Score enrichment output.

python -m src.eval --input ./data/gold/assessments --out ./docs/eval.md
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import logging
from pathlib import Path

from .report import build_report, to_markdown

LOG = logging.getLogger(__name__)


def load_enriched(path: str) -> list[dict]:
    """Read gzipped newline-delimited enrichment output."""
    files = sorted(glob.glob(f"{path}/**/*.json.gz", recursive=True))
    records: list[dict] = []
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(json.loads(line))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Score enrichment against labels")
    parser.add_argument("--input", default="./data/gold/assessments")
    parser.add_argument("--out", default="./docs/eval.md")
    parser.add_argument("--json-out", default="./data/gold/_eval/metrics.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    records = load_enriched(args.input)
    if not records:
        print(f"No enrichment output under {args.input}. Run: make enrich-local")
        return 1

    report = build_report(records)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(to_markdown(report))

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_bytes(report.to_json())

    m, b = report.metrics, report.baseline
    print()
    print(f"  n scored          {report.n_scored}")
    print(f"  accuracy          {m['accuracy']:.1%}")
    print(
        f"  baseline          {b['majority_accuracy']:.1%}  "
        f"(always predict '{b['majority_class']}')"
    )
    print(f"  lift              {b['lift_over_baseline']:+.1%}")
    print(f"  cohens kappa      {m['cohens_kappa']:.3f}")
    print(f"  precision/recall  {m['precision']:.1%} / {m['recall']:.1%}")
    print(
        f"  hallucination     {report.hallucination['rate']:.1%} "
        f"({report.hallucination['invented']}/{report.hallucination['checked']})"
    )
    print(f"  p95 latency       {report.performance['p95_latency_ms']:.0f} ms")
    print()
    if not b["beats_baseline"]:
        print("  The model did not beat the majority-class baseline.")
        print("  That is a real result. Publish it and explain why.")
    print(f"  Written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
