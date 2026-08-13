# Streaming slice

## What this is, precisely

A Kafka producer and consumer written against the standard `confluent-kafka`
client (librdkafka), running against Redpanda in Docker. Redpanda implements
the Kafka protocol, so the client code is genuine Kafka code.

**It is not managed MSK.** Nothing here is deployed to AWS. That distinction is
stated plainly because it holds up under questioning and the alternative does
not.

## Delivery semantics

At-least-once, by construction.

The consumer runs with `enable.auto.commit=False` and commits offsets only
after the batch has been durably written:

```
poll -> accumulate -> write batch to storage -> commit offsets
```

The ordering is the entire design. Committing before the write would mean a
crash between the two silently loses a batch - the offsets say those records
were handled, so they are never redelivered. Committing after means a crash
replays the batch instead.

**The consequence is duplicates, and they are accepted deliberately.** A crash
between write and commit produces a batch written twice. This is why the
silver layer deduplicates on `safetyreportid`, keeping the record with the
latest `receiptdate`, rather than assuming the stream is clean.

Exactly-once would require Kafka transactions with a transactional sink. S3 is
not transactional, so the honest options are at-least-once plus downstream
dedup, or a two-phase commit that is not worth the complexity here.

## Partitioning

Messages are keyed on `safetyreportid`. Keying does two things:

1. All messages for one report land on the same partition, so their relative
   order is preserved. Unkeyed messages round-robin, and an amended report
   could be processed before the original it amends.
2. It makes the dedup key and the partition key the same field, so duplicates
   from a replay always arrive on the same partition.

## Producer idempotence

`enable.idempotence=True` prevents the producer's own internal retries from
writing the same record twice. It says nothing about consumer-side duplicates -
different failure, different mechanism. Conflating the two is a common mistake.

## What would change on MSK

| Concern | Local Redpanda | Managed MSK |
|---|---|---|
| Broker ops | `docker compose up` | Cluster sizing, patching, scaling |
| Auth | None | IAM auth or SASL/SCRAM |
| Network | localhost | VPC, security groups, private subnets |
| Consumer runtime | Local process | ECS/Fargate task or Lambda event source |
| Cost | Zero | Meaningful, even for MSK Serverless |
| Rebalancing | Single consumer | Real rebalances under partition reassignment |

The code would largely survive the move. The operational surface would not.

## Known limitations

- Single consumer, so rebalance behaviour is untested against real reassignment
- No schema registry; messages are raw JSON with no compatibility guarantees
- No dead letter topic; a poison message would fail the batch repeatedly
- `max.poll.interval.ms` is generous; a slow S3 write could still trigger a
  rebalance under sustained load
