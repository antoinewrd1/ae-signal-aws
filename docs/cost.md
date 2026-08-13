# Cost

Target: under $10/month. Ceiling enforced by `infra/budget.tf` at $25.

| Service | Driver | Controls in place |
|---|---|---|
| Glue | ~$0.44/DPU-hr, 10-minute minimum per run | Spark developed locally in Docker. Glue runs are counted, not scheduled. |
| Bedrock | Per-token, Claude Haiku | Enrichment capped at 2,000 records. Responses cached by content hash. |
| S3 | Storage + requests | Parquet with lifecycle expiry on bronze. |
| Lambda / Step Functions / EventBridge | Invocations | Negligible at this volume. |
| RDS / OpenSearch | Would dominate the bill | Deliberately not used. Vector search runs on local FAISS. |

## Running total

| Date | Actual spend | Note |
|---|---|---|
| | | |

## Habits

- EventBridge schedules stay disabled unless actively testing
- `make tf-destroy` at the end of a work session
