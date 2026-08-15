# Architecture

## Why these components

The brief was AWS-native serverless data automation with a generative AI step.
Each choice below is the cheapest thing that does the job, with the alternative
noted where the decision would flip at scale.

## Ingestion

**openFDA drug adverse event API.** Public, no authentication at low volume,
and genuinely messy: deeply nested optional fields, three different date
precisions encoded in companion `*dateformat` columns, and a hard pagination
cap. A clean CSV would have demonstrated nothing.

**Lambda, standard library only.** The extractor uses `urllib.request` rather
than `requests`, so the deployment package is source with no pip step, no
layer, and no possibility of local and deployed dependencies diverging. That
constraint removes an entire category of deployment failure — one the
enrichment Lambda, which does have a compiled dependency, went on to
demonstrate.

**Date-window partitioning.** openFDA refuses to paginate past `skip=25000`, so
a broad query is genuinely unreachable past that point. Queries are split into
weekly windows, and `PaginationExhaustedError` raises loudly if a window is
still too wide rather than silently truncating.

**Run manifests.** Every extraction writes query parameters, record count,
request count, duration, and a content checksum alongside the data. This is
what makes "did it run correctly?" answerable after the fact rather than a
matter of trust.

## Streaming

Kafka producer and consumer against Redpanda in Docker. Real Kafka client code,
real broker, not managed MSK — stated plainly because the alternative does not
survive questioning.

Delivery is **at-least-once by construction**: offsets commit only after a
batch is durably written. Committing first would turn a crash into silent data
loss. Committing after means a crash replays the batch instead, which is why
the silver layer deduplicates on `safetyreportid`. Full reasoning in
[streaming.md](streaming.md).

## Transform

**Three silver tables, not one.** A report with 8 drugs and 6 reactions
exploded into a single table becomes 48 rows, inflating every downstream count.
`silver_report`, `silver_drug`, and `silver_reaction` stay normalised; gold
joins them *within* a report, where the product is exactly the relationship
being measured.

**Explicit schema, never inferred.** Inference means the schema silently
changes when the sample does, which openFDA's optional nested fields make
near-certain. An explicit schema turns a schema change into a diff in version
control.

**Partial dates are not invented.** Month-precision resolves to the first of
the month with `receipt_date_precision` recorded alongside; year-only becomes
null. Fabricating precision you do not have is worse than a null.

**Quality gates raise.** A check that only logs is a check that gets ignored —
the job goes green, bad data lands, and the problem surfaces three layers
downstream where nobody can trace it.

**The transform materialises the enrichment input.** Spark writes
`silver/enrichment_input/` as newline-delimited JSON so the enrichment step
needs no Spark at all. It reads plain JSON in a Lambda instead of paying for a
cluster to redo a join that has already happened.

## Enrichment

**The task has verifiable ground truth.** Asking a model to summarise produces
output nobody can grade. Asking it to predict seriousness from reaction terms —
with the report's own seriousness flag withheld from the prompt — produces a
prediction scoreable against a label that already exists. That single decision
is what makes the eval harness possible.

**Tool use, not "return JSON".** Bedrock's `toolChoice` forces a call to
`record_assessment`, constraining the response shape at the API level. Pydantic
revalidates afterward, because a schema constrains structure and not semantics.

**Nothing is dropped.** Records failing validation twice land in `gold/_dlq/`
with reason and attempt count, and `success_rate` divides by everything
attempted rather than by successes.

**Model ID is configuration, logged per record.** Model IDs get retired — this
project outlived one during its build. A hardcoded ID is a silent breakage
waiting for the next release cycle, and eval results are unattributable without
the model and prompt version stored beside them.

## Orchestration

Step Functions chains extract → quality gate → transform → enrich.

**The quality gate is a Choice state.** Zero records routes to `NoNewData` and
succeeds without touching Glue. Running Spark on an empty prefix costs the same
as running it on real data and produces empty everything plus a green check.

**`startJobRun.sync`, not fire-and-forget.** Blocks until Glue reaches a
terminal state, so enrichment cannot run against stale or half-written silver.

**`NotifyFailure` publishes, then fails.** It routes to a `Fail` state rather
than `Succeed`, so the execution records as failed and the alarm fires.
Notifying and then succeeding is a common mistake that makes a dashboard lie.

## Gold layer and the PRR caveat

The gold layer computes the Proportional Reporting Ratio per drug–reaction
pair, with a Haldane–Anscombe continuity correction when any cell of the
contingency table is zero — without it, the strongest signals return null and
disappear.

**PRR is a screening heuristic and nothing more.** Spontaneous reporting data
has no denominator, no control group, and severe reporting bias: publicity
about a drug increases reports about that drug. A high PRR flags a pair worth a
human looking at it. It is not evidence of causation and nothing in this
repository should be read as if it were.

## What is not here

- EMR, Azure, Amazon Connect, Kubernetes, FedRAMP or PCI-DSS controls
- Schema registry on the Kafka topic
- Vector search or RAG
- Drift detection on the deployed infrastructure
