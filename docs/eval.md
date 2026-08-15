# Evaluation results

Generated 2026-08-15T18:53:34+00:00
Model `us.anthropic.claude-haiku-4-5-20251001-v1:0` | prompt `v1` | n=20 scored, 0 unlabeled

## Headline

| Metric | Value |
|---|---|
| Accuracy | 85.0% |
| **Majority-class baseline** | **70.0%** |
| **Lift over baseline** | **+15.0%** |
| Cohen's kappa | 0.625 |

> Accuracy alone is not interpretable here. The baseline is the accuracy
> of always predicting `serious`. A model that does not beat it
> has learned nothing, however high the raw accuracy looks. Kappa corrects
> for chance agreement: 0 is chance-level, negative is worse than chance.

## Classification detail

Positive class: `serious`

| Metric | Value |
|---|---|
| Precision | 86.7% |
| Recall | 92.9% |
| Specificity | 66.7% |
| F1 | 0.897 |

| | Predicted serious | Predicted non-serious |
|---|---|---|
| **Actually serious** | 13 | 1 |
| **Actually non-serious** | 2 | 4 |

## Calibration

| Stated confidence | n | Accuracy |
|---|---|---|
| high | 17 | 82.3% |
| medium | 3 | 100.0% |

> If accuracy does not fall as confidence drops, the confidence field is
> decoration and should not be used to filter or route.

## Hallucination

Predicted a substance absent from the report's own drug list in **1 of 16** cases (6.2%). Abstained (returned null) 4 times.

> Abstention is not counted as failure. Declining when the input is
> ambiguous is correct behaviour, and penalising it would reward guessing.

## Performance and cost

| Metric | Value |
|---|---|
| p50 latency | 1882 ms |
| p95 latency | 3680 ms |
| Input tokens | 21,965 |
| Output tokens | 3,335 |

## Interpretation

**The sample is too small to support the headline.** The 95% Wilson interval
on 17/20 correct runs from roughly 64% to 95%, and the 70% baseline falls
inside it. The +15 point lift is three records — the baseline gets 14 right,
the model gets 17. At n=20 this result is directionally encouraging and
statistically indistinguishable from predicting the majority class every time.

**Where it fails.** Specificity is 66.7%: four of six non-serious reports were
identified correctly. Recall is 92.9% against that, so the model
systematically over-predicts `serious`. Given a 70% base rate that is the
cheap direction to err, and it is also the direction that makes the accuracy
figure look better than the model deserves. The two false positives matter
more than the single false negative for judging whether it learned the task.

**Calibration is inverted.** Records the model marked `high` confidence scored
82.3%; `medium` scored 100%. The medium bucket holds three records so this is
almost certainly noise, but as measured the confidence field carries no usable
signal and should not be used to route or filter.

**Hallucination is low but nonzero.** One of sixteen named suspects did not
appear in its own report's drug list. Four abstentions out of twenty is a 20%
abstention rate, which reads as appropriate caution rather than evasion.

**What I would do next**

1. Label 200+ records. Nothing else here is worth tuning until the interval is
   narrow enough to distinguish the model from the baseline.
2. Report confidence intervals alongside every point estimate in this file.
3. Stratify the sample to include more non-serious reports. Six negatives
   cannot support a specificity estimate.
4. Only then vary the prompt, and treat each version as a separate experiment
   with its own `PROMPT_VERSION`.

**On the cost figure.** The per-token rates are configuration, not measured.
Verify them against current Bedrock pricing before quoting the
cost-per-1k number anywhere.
