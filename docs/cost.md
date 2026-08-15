# Cost

**Total spend across the entire build: under $2**, including roughly eight Glue
runs, several hundred Bedrock calls, and a fully deployed stack torn down and
rebuilt half a dozen times.

## A correction worth recording

Early planning for this project assumed AWS Glue bills a **10-minute minimum**
per job run. That is true of Glue 0.9 and 1.0. **Glue 2.0 and later bill a
1-minute minimum**, and the observed `DPUSeconds` on real runs confirms
near-actual billing:

| Run | DPU-seconds | Cost at $0.44/DPU-hour |
|---|---|---|
| Failed on import (37s) | 74 | $0.009 |
| Failed on IAM (74s) | 149 | $0.018 |
| Succeeded (131s) | 262 | $0.032 |

The estimate was off by roughly two orders of magnitude, which materially
changed how cautious it was worth being about re-running the transform. Worth
recording because a cost model built on a stale assumption produces confidently
wrong engineering decisions — in this case, avoiding iteration that was
effectively free.

## Where the money actually goes

| Service | Driver | Observed | Control |
|---|---|---|---|
| Glue | $0.44/DPU-hour, 2× G.1X, 1-min minimum | ~$0.03/run | Spark developed locally in Docker; Glue runs counted, never scheduled |
| Bedrock | Per-token, Claude Haiku | ~$0.04 per 20 records | `ENRICH_LIMIT` caps every run; responses cached by content hash locally |
| S3 | Storage + requests | cents | 90-day lifecycle expiry on bronze; incomplete uploads aborted after 3 days |
| Lambda | Invocations + duration | negligible | Free tier covers this volume entirely |
| Step Functions | State transitions | negligible | Standard workflows, few states |
| CloudWatch | Logs + dashboard | cents | 14-day retention on every log group |
| RDS / OpenSearch / MSK | Would dominate everything above | **$0** | Deliberately not used |

The single largest cost decision was **not** using managed services that bill
by the hour. MSK Serverless, an RDS instance for pgvector, or OpenSearch
Serverless would each have cost more per day idle than this entire project cost
to build.

## Controls, in the order they were added

1. **Budget alarm deployed before any billable resource.** The first Terraform
   apply in this repository creates a $25 monthly budget with alerts at 40% and
   80% actual and 100% forecasted. The forecast alarm is the one that catches a
   runaway schedule before the bill arrives.
2. **EventBridge schedule disabled by default.** `enable_schedule` defaults to
   `false`. A forgotten cron trigger is the most plausible way this project
   generates an unexpected bill.
3. **Hard record caps on every model call.** `ENRICH_LIMIT` defaults to 50 and
   is overridable per invocation. Every record is a billed Bedrock call.
4. **Response caching keyed on model, prompt version, and content.** Protects
   the development loop from re-billing identical requests, and correctly
   misses when the prompt changes so evaluation never scores a stale prompt.
5. **Quality gate before the expensive step.** If extract returns zero records,
   the Choice state skips Glue entirely rather than paying to process nothing.
6. **`force_destroy = false` on the bucket.** Teardown refuses on a non-empty
   bucket rather than silently discarding data. The friction is deliberate.

## Teardown

Versioning is enabled on the bronze bucket, so `aws s3 rm --recursive` does not
empty it — it writes delete markers, which are themselves objects. The bucket
reads as empty and `DeleteBucket` still returns `BucketNotEmpty`.

```bash
./scripts/empty-bucket.sh $(terraform -chdir=infra output -raw bronze_bucket)
make tf-destroy
```
