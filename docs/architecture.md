# Architecture

> Filled in on day 8. Diagram source lives in this directory and is committed
> alongside the exported image.

## Intended flow

```
EventBridge (schedule, disabled by default)
      |
      v
  Lambda (extract)  --> S3 bronze/   raw openFDA JSON, partitioned by ingest date
      |
      |  [parallel path]
Redpanda producer --> topic --> consumer --> S3 bronze-stream/
      |
      v
  Glue PySpark      --> S3 silver/   flattened, typed, deduped Parquet
      |                              +-> Glue Data Catalog -> Athena
      v
  Lambda (enrich)   --> Bedrock (Claude Haiku) --> S3 gold/  validated JSON
      |
      v
  Eval harness      --> metrics.json  accuracy, cost/1k, p95 latency

Orchestrated by Step Functions. Defined in Terraform. Deployed by GitHub Actions.
```

## Design decisions to write up

- Glue vs EMR for this workload, and where the crossover point is
- Local Redpanda vs managed MSK, and what changes in production
- Where the pipeline breaks at 100x volume
