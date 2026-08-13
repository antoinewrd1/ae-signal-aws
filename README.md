# AE-Signal

A serverless data automation pipeline on AWS that ingests FDA adverse event
reports, transforms them through a medallion layout, enriches free-text
narratives with Amazon Bedrock, and scores that enrichment against a
hand-labeled ground truth set.

The point of the eval harness is the part I care most about: the GenAI step is
measured rather than assumed.

---

## Status

This section is kept accurate as the build progresses. **If a component is not
listed as Done, the code for it is not in this repo.**

| Component | Status |
|---|---|
| Repo scaffold, Terraform backend, cost guardrails | Done |
| openFDA extractor — Lambda to S3 bronze | Done |
| Kafka-API streaming ingestion (Redpanda, local) | Not started |
| Glue PySpark transform — bronze to silver to gold | Not started |
| Bedrock enrichment with schema validation | Not started |
| Eval harness with labeled ground truth | Not started |
| Step Functions orchestration | Not started |
| CI/CD — GitHub Actions | Not started |
| Architecture docs, cost analysis, results | Not started |

## Scope and limitations

Stated up front so nothing here is oversold:

- Streaming runs locally via Redpanda in Docker. **Not deployed to MSK.**
- Spark runs on AWS Glue. **No EMR cluster experience is claimed here.**
- Single cloud. No Azure components.
- All data is public. No PHI, and no HIPAA controls are implemented in this project.

## Data source

openFDA drug adverse event API — <https://api.fda.gov/drug/event.json>

Public, no authentication required at low volume. A free API key raises rate
limits and is recommended: <https://open.fda.gov/apis/authentication/>

## Quickstart

```bash
make install          # dev dependencies
make lint             # ruff + black --check
make test             # pytest
./scripts/bootstrap-backend.sh   # one-time: create the Terraform state bucket
make tf-init
make tf-plan
```

## Cost

Designed to run for well under $10/month. See [docs/cost.md](docs/cost.md).
Budget alerts are managed in Terraform (`infra/budget.tf`), not set by hand.

## Documentation

- [Architecture](docs/architecture.md)
- [Cost analysis](docs/cost.md)
- [Incidents and root cause writeups](docs/incidents.md)
