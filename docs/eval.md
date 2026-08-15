# Evaluation results

Generated 2026-08-15T23:33:13+00:00
Model `us.anthropic.claude-haiku-4-5-20251001-v1:0` | prompt `v1` | n=40 scored, 0 unlabeled

## Headline

| Metric | Value |
|---|---|
| Accuracy | 85.0% |
| **Majority-class baseline** | **55.0%** |
| **Lift over baseline** | **+30.0%** |
| Cohen's kappa | 0.694 |

> Accuracy alone is not interpretable here. The baseline is the accuracy
> of always predicting `serious`. A model that does not beat it
> has learned nothing, however high the raw accuracy looks. Kappa corrects
> for chance agreement: 0 is chance-level, negative is worse than chance.

## Classification detail

Positive class: `serious`

| Metric | Value |
|---|---|
| Precision | 83.3% |
| Recall | 90.9% |
| Specificity | 77.8% |
| F1 | 0.870 |

| | Predicted serious | Predicted non-serious |
|---|---|---|
| **Actually serious** | 20 | 2 |
| **Actually non-serious** | 4 | 14 |

## Calibration

| Stated confidence | n | Accuracy |
|---|---|---|
| high | 30 | 83.3% |
| medium | 10 | 90.0% |

> If accuracy does not fall as confidence drops, the confidence field is
> decoration and should not be used to filter or route.

## Hallucination

Predicted a substance absent from the report's own drug list in **3 of 34** cases (8.8%). Abstained (returned null) 6 times.

> Abstention is not counted as failure. Declining when the input is
> ambiguous is correct behaviour, and penalising it would reward guessing.

## Performance and cost

| Metric | Value |
|---|---|
| p50 latency | 1697 ms |
| p95 latency | 2671 ms |
| Input tokens | 43,366 |
| Output tokens | 6,730 |

## Interpretation

_Write the honest reading here, including where it fails and what you
would try next. Publish whatever the numbers are._
