"""Assembles enriched records into a scored report."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .metrics import (
    calibration,
    cohens_kappa,
    confusion,
    hallucination,
    majority_baseline,
    percentile,
)

POSITIVE_CLASS = "serious"


@dataclass
class EvalReport:
    generated_at: str
    model_id: str
    prompt_version: str
    n_scored: int
    n_unlabeled: int
    metrics: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    calibration: list[dict] = field(default_factory=list)
    hallucination: dict = field(default_factory=dict)
    performance: dict = field(default_factory=dict)

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), indent=2).encode("utf-8")


def build_report(enriched: list[dict]) -> EvalReport:
    """Score enriched records against the labels carried alongside them."""
    scored = [r for r in enriched if r.get("label_seriousness")]
    unlabeled = len(enriched) - len(scored)

    y_true = [r["label_seriousness"] for r in scored]
    y_pred = [r["assessment"]["seriousness"] for r in scored]

    matrix = confusion(y_true, y_pred, POSITIVE_CLASS)
    baseline_label, baseline_acc = majority_baseline(y_true)
    kappa = cohens_kappa(y_true, y_pred)

    cal_input = [
        {
            "confidence": r["assessment"].get("confidence"),
            "predicted": r["assessment"]["seriousness"],
            "actual": r["label_seriousness"],
        }
        for r in scored
    ]

    hall_input = [
        {
            "safetyreportid": r.get("safetyreportid"),
            "predicted_suspect": r["assessment"].get("primary_suspect"),
            "input_substances": r.get("input_substances") or [],
        }
        for r in enriched
    ]
    hall = hallucination(hall_input)

    latencies = [float(r.get("latency_ms", 0)) for r in enriched if not r.get("cached")]
    in_tokens = sum(int(r.get("input_tokens", 0)) for r in enriched)
    out_tokens = sum(int(r.get("output_tokens", 0)) for r in enriched)

    first = enriched[0] if enriched else {}

    return EvalReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model_id=first.get("model_id", "unknown"),
        prompt_version=first.get("prompt_version", "unknown"),
        n_scored=len(scored),
        n_unlabeled=unlabeled,
        metrics={**matrix.to_dict(), "cohens_kappa": round(kappa, 4)},
        baseline={
            "majority_class": baseline_label,
            "majority_accuracy": round(baseline_acc, 4),
            # The only figure that says whether the model beat a constant.
            "lift_over_baseline": round(matrix.accuracy - baseline_acc, 4),
            "beats_baseline": matrix.accuracy > baseline_acc,
        },
        calibration=[
            {"confidence": b.confidence, "n": b.n, "accuracy": round(b.accuracy, 4)}
            for b in calibration(cal_input)
        ],
        hallucination={
            "checked": hall.checked,
            "invented": hall.invented,
            "abstained": hall.abstained,
            "rate": round(hall.rate, 4),
            "examples": hall.examples,
        },
        performance={
            "p50_latency_ms": round(percentile(latencies, 50), 1),
            "p95_latency_ms": round(percentile(latencies, 95), 1),
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
        },
    )


def to_markdown(report: EvalReport) -> str:
    m, b = report.metrics, report.baseline
    lines = [
        "# Evaluation results",
        "",
        f"Generated {report.generated_at}",
        f"Model `{report.model_id}` | prompt `{report.prompt_version}` | "
        f"n={report.n_scored} scored, {report.n_unlabeled} unlabeled",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Accuracy | {m['accuracy']:.1%} |",
        f"| **Majority-class baseline** | **{b['majority_accuracy']:.1%}** |",
        f"| **Lift over baseline** | **{b['lift_over_baseline']:+.1%}** |",
        f"| Cohen's kappa | {m['cohens_kappa']:.3f} |",
        "",
        "> Accuracy alone is not interpretable here. The baseline is the accuracy",
        f"> of always predicting `{b['majority_class']}`. A model that does not beat it",
        "> has learned nothing, however high the raw accuracy looks. Kappa corrects",
        "> for chance agreement: 0 is chance-level, negative is worse than chance.",
        "",
        "## Classification detail",
        "",
        f"Positive class: `{POSITIVE_CLASS}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {m['precision']:.1%} |",
        f"| Recall | {m['recall']:.1%} |",
        f"| Specificity | {m['specificity']:.1%} |",
        f"| F1 | {m['f1']:.3f} |",
        "",
        "| | Predicted serious | Predicted non-serious |",
        "|---|---|---|",
        f"| **Actually serious** | {m['tp']} | {m['fn']} |",
        f"| **Actually non-serious** | {m['fp']} | {m['tn']} |",
        "",
        "## Calibration",
        "",
        "| Stated confidence | n | Accuracy |",
        "|---|---|---|",
    ]
    for bucket in report.calibration:
        lines.append(f"| {bucket['confidence']} | {bucket['n']} | {bucket['accuracy']:.1%} |")

    h = report.hallucination
    lines += [
        "",
        "> If accuracy does not fall as confidence drops, the confidence field is",
        "> decoration and should not be used to filter or route.",
        "",
        "## Hallucination",
        "",
        f"Predicted a substance absent from the report's own drug list in "
        f"**{h['invented']} of {h['checked']}** cases ({h['rate']:.1%}). "
        f"Abstained (returned null) {h['abstained']} times.",
        "",
        "> Abstention is not counted as failure. Declining when the input is",
        "> ambiguous is correct behaviour, and penalising it would reward guessing.",
        "",
        "## Performance and cost",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| p50 latency | {report.performance['p50_latency_ms']:.0f} ms |",
        f"| p95 latency | {report.performance['p95_latency_ms']:.0f} ms |",
        f"| Input tokens | {report.performance['input_tokens']:,} |",
        f"| Output tokens | {report.performance['output_tokens']:,} |",
        "",
        "## Interpretation",
        "",
        "_Write the honest reading here, including where it fails and what you",
        "would try next. Publish whatever the numbers are._",
        "",
    ]
    return "\n".join(lines)
