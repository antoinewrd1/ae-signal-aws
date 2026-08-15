# Incidents and root cause writeups

Real failures encountered while building this, what caused them, and what
changed as a result. Written for the same reason a production runbook is:
the fix is less interesting than the diagnosis.

## Template

**Symptom** — what was observed, and how it surfaced
**Impact** — what broke, and what was still working
**Root cause** — the actual cause, not the first plausible one
**Fix** — what changed
**Prevention** — the test, alarm, or gate that would have caught it earlier

---

_No incidents recorded yet._

## Bedrock enrichment failed for every record: account use-case gate

**Symptom** — The first real enrichment run dead-lettered all 20 records.
Every one returned the same `ResourceNotFoundException` from the Converse
API: "Model use case details have not been submitted for this account."

**Impact** — No data written to `gold/assessments/`. No partial or corrupted
output. The eval harness had nothing to score, which is the correct outcome —
scoring zero records would have been worse than scoring none.

**Root cause** — Not a code defect. Anthropic models on Bedrock require a
one-time use-case submission per AWS account, separate from the newer
auto-enable-on-invoke behaviour for serverless foundation models. The account
had never submitted it. The error surfaces per-request, so a permanent
account-level condition presented as twenty independent failures.

**Fix** — Submitted the use-case details form in the Bedrock console and
re-ran after the stated 15-minute propagation window.

**Prevention** — Verify model reachability before a batch run rather than
discovering it per record:

    aws bedrock-runtime converse --region us-east-1 \
      --model-id "$BEDROCK_MODEL_ID" \
      --messages '[{"role":"user","content":[{"text":"ok"}]}]'

Worth adding to `scripts/preflight.sh` so it is checked once, cheaply, before
anything that costs money.

**What this validated**

The failure was more useful than a success would have been, because it
exercised three design decisions under real conditions:

- `ResourceNotFoundException` is not in `RETRYABLE`, so the client failed
  immediately instead of spending four exponential-backoff retries per record
  on a condition that could never resolve within the run. Twenty records
  failed in 3.7 seconds rather than several minutes.
- All twenty landed in `gold/_dlq/` with their reason and attempt count. No
  record was silently dropped, so the input count and the output count still
  reconcile.
- `success_rate` reported `0.0`, not `1.0`. The metric divides by everything
  attempted rather than by successes — computed the other way it would have
  reported perfect success on a run that produced nothing. This is what
  `test_success_rate_denominator_includes_failures` guards.
