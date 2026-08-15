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

## Glue job failed on import: local layout is not the deployed layout

**Symptom** — The first deployed Glue run failed after 33 seconds with
`ImportError: attempted relative import with no known parent package`. The
same code had run clean locally and passed 51 unit tests.

**Impact** — One failed Glue run, billed at the 10-minute minimum. No data
written. Nothing corrupted.

**Root cause** — Locally the job runs as `python -m src.transform.job`, so
`src.transform` is a real package and `from .gold import ...` resolves against
it. On Glue the script is fetched standalone from S3 and its dependencies come
from `--extra-py-files`, which unpacks with `transform/` at the top level.
There is no parent package, so every relative import in the module fails.

**Fix** — Relative imports attempted first, with an absolute fallback:

    try:
        from .gold import build_gold_signals
    except ImportError:
        from transform.gold import build_gold_signals

Relative stays the default because that is the path the test suite exercises;
absolute is the fallback for the deployed layout only.

**Prevention** — No unit test could have caught this, and that is the point.
The tests import the module the way the local interpreter constructs it, so
they validate logic while saying nothing about the module tree the deployment
target builds. Catching it requires either running against the real packaging
or asserting on the deployed artifact's structure.

**Generalisation** — A green test suite is evidence about behaviour, not about
deployment topology. Packaging, import paths, runtime versions, and filesystem
layout are all outside what tests observe by construction.

---

## Twenty-one test failures, one environment variable

**Symptom** — Every Spark test failed at once with
`PYTHON_VERSION_MISMATCH: Python in worker has different version: 3.14 than
that in driver: 3.12`. Twenty-one failures across three files, appearing to
implicate the silver transforms, the gold aggregations, and the quality gates
simultaneously.

**Impact** — Local development blocked. Nothing wrong with the code.

**Root cause** — Spark's driver ran inside the project virtualenv on Python
3.12. Spark launches its Python workers as separate processes using whatever
`python3` resolves to on `PATH`, which was the system interpreter on 3.14.
Spark requires driver and workers to match on the minor version and refuses
to run when they do not. The breadth of the failure was misleading: every
test touches a Spark action, so a single environment fault presented as a
wholesale collapse.

**Fix** — Pinned both ends to the running interpreter in `tests/conftest.py`
and in the local branch of the transform entrypoint:

    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

`setdefault` rather than assignment, so an explicit override in the
environment still wins.

**Prevention** — The fix lives in the repository, not in a shell profile.
Exporting the variables in `.bashrc` would have worked on this machine and
silently broken for anyone else who cloned the project. Environment setup that
the code depends on is part of the code.

**Generalisation** — Managed Spark sets this correctly, so the problem only
appears in local development. That inverts the usual assumption: here the
development environment is the less consistent one, and prod hides a class of
bug that dev exposes.

---

## terraform destroy blocked by a bucket that looked empty

**Symptom** — `terraform destroy` failed with
`BucketNotEmpty: The bucket you tried to delete is not empty. You must delete
all versions in the bucket` — immediately after
`aws s3 rm s3://<bucket> --recursive` had reported deleting every object.

A second error surfaced in the same run: `AccessDenied` on
`iam:ListInstanceProfilesForRole` while deleting the Lambda execution role.

**Impact** — Teardown left partially complete. Nine of thirteen resources
destroyed; the bucket and one IAM role remained, continuing to accrue
(negligible) cost. Terraform state and reality diverged until the retry.

**Root cause, bucket** — Versioning is enabled on the bronze bucket, which is
deliberate: it protects against a bad pipeline run overwriting good data.
On a versioned bucket, `s3 rm` does not remove objects. It writes delete
markers, which hide the current version while every prior version and every
marker remains as a real object. The bucket reads as empty through the normal
listing API and is not empty at all. `force_destroy` was set to `false`, which
is correct — a bucket that silently discards data on `terraform destroy` is a
footgun — so S3 refused the deletion.

**Root cause, IAM** — The deployer policy was scoped least-privilege and
granted the actions needed to *create* a role. The AWS provider calls
`iam:ListInstanceProfilesForRole` when *deleting* one, to check nothing is
attached. That action had never been granted because nothing had ever tried
to delete a role before.

**Fix** — Enumerate and delete every version and delete marker before
destroying, and add the missing IAM actions to the deployer policy.

**Prevention** — Both moved into the repository: a `scripts/empty-bucket.sh`
helper, and the corrected policy committed to `iam/` rather than edited only
in the console, where it would have drifted invisibly.

**Generalisation** — Least-privilege policies fail at teardown rather than at
creation, because delete paths call APIs that create paths never touch. A
policy validated by a successful `apply` is only half tested; the destroy path
is the other half, and it is the half nobody exercises until they need it.

## Extract default window returned zero rows year-round

**Symptom** — The first scheduled-shape pipeline run succeeded in seconds with
`record_count: 0`. The Choice state routed to `NoNewData`, Glue never ran, and
the execution was correctly marked SUCCEEDED.

**Impact** — None. No spend, no partial output, no false success signal. But a
scheduled run would have done nothing, every day, indefinitely.

**Root cause** — The extract handler defaulted to a window ending 30 days
before today. openFDA publishes FAERS on a lag measured in months, not weeks,
so that window is reliably empty. Every prior successful run had passed
explicit 2024 dates, which hid the defect completely.

**Fix** — Default lag raised to 180 days and made configurable via
`EXTRACT_LAG_DAYS`, still overridable per-invocation for backfills.

**Prevention** — Assumptions about upstream publication lag belong in a named,
documented constant rather than a literal inside a default argument.

**What this validated** — The quality gate did exactly its job. Running Glue
on an empty bronze prefix costs the same ten-minute minimum as running it on
real data and produces empty silver, empty gold, and a green checkmark. The
Choice state turned a silent waste into a visible, free no-op.

---

## The same Glue import bug, twice

**Symptom** — `ImportError: attempted relative import with no known parent
package` — the identical failure already diagnosed, fixed, and written up
during the transform build.

**Impact** — One failed Glue run at the ten-minute billing minimum. Enrichment
never ran, so no Bedrock spend.

**Root cause** — Not the import mechanics, which were understood. The fix
existed in one working copy and was overwritten when a later change to the
same file landed from a different source. The corrected version had never been
propagated back into the copy that changes were being cut from.

**Fix** — Reapplied, and applied at the source so subsequent changes carry it.

**Prevention** — Verify a known fix is still present before deploying, not
after a run fails. `grep -c` against the specific markers is a two-second
check; the Glue run that catches its absence costs ten minutes of billing and
several minutes of waiting.

**Generalisation** — A fix that lives in one working copy is not a fix. This is
the same lesson as committing environment setup rather than exporting it in a
shell profile, arriving from the opposite direction: the correction was in
version control, but the file it lived in was being replaced wholesale rather
than merged.

---

## IAM denied the write after Spark had done all the work

**Symptom** — The Glue job ran for 74 seconds, read bronze, executed every
transform, and then failed writing Parquet:

    s3:PutObject on "ae-signal-dev-bronze-.../silver_$folder$" -- AccessDenied

**Impact** — One failed run at the billing minimum, with the compute fully
consumed before the failure. Nothing written, nothing corrupted.

**Root cause** — The Glue role's write permission was scoped to
`silver/*` and `gold/*`. Hadoop, writing to object storage that has no real
directories, creates zero-byte marker objects named `<prefix>_$folder$`. That
key is a *sibling* of the prefix, not a child: `silver_$folder$` does not match
`silver/*`. IAM resource matching is literal string matching, not path
semantics, and the two look identical to a reader.

**Fix** — Added `silver_*` and `gold_*` to the resource list.

**Prevention** — When scoping S3 permissions for a Hadoop or Spark writer,
account for marker objects alongside the data prefix. The general rule: what a
framework writes is not limited to what you asked it to write.

**Cost of the failure mode** — Write permissions are exercised last. A missing
write permission therefore fails after the entire job has been paid for, which
makes it the most expensive category of permission error to discover by
running into it.

---

## A completely successful job reported as FAILED

**Symptom** — The Glue run executed for 131 seconds, passed all eight quality
gates, and wrote silver, gold, and the enrichment input to S3. Step Functions
reported the task as failed with `ErrorMessage: "SystemExit: 0"`. The failure
notification fired, downstream states were skipped, and the alarm triggered.

**Impact** — The most damaging of any incident in this project. Every output
was correct and present in S3, while the pipeline's own reporting said the run
had failed. Enrichment was skipped, an alert was sent, and an operator reading
the dashboard would have concluded the transform was broken.

**Root cause** — The module ended with `raise SystemExit(main())`, the
conventional and correct Python CLI entrypoint. Glue's script wrapper treats
**any** `SystemExit` as a job failure, including `SystemExit(0)`. Success and
failure were therefore indistinguishable to the platform.

**Fix** — Fall off the end of the module on success; raise only on a non-zero
code, so genuine failures — including a tripped quality gate — still surface.

**Prevention** — Verify that a runtime's success signal matches what the code
emits. "Exit code 0 means success" is a shell convention, not a universal one.

**Why this one matters most** — An import error fails loudly and immediately.
A wrong number in a manifest is discoverable by inspection. A success reported
as a failure is worse than either, because it trains an operator to distrust
their own monitoring. Once alerts are assumed to be noise, the next real
failure is invisible.

---

## Least privilege, five times

Not a single incident but a pattern, recorded because the pattern is the point.

Five separate permission gaps surfaced during this build, each only when a code
path executed for the first time:

| Missing permission | Surfaced when |
|---|---|
| `iam:ListInstanceProfilesForRole` | first `terraform destroy` |
| `bedrock:InvokeModel` (account use-case gate) | first enrichment run |
| `aws-marketplace:Subscribe` | first enrichment run after the gate cleared |
| `iam:CreateOpenIDConnectProvider` | first CI role deployment |
| `s3:PutObject` on `silver_$folder$` | first Glue write |

None was predictable from reading the policy. Creating a role does not exercise
deleting one; invoking a model does not exercise subscribing to it; writing to
a prefix does not exercise writing its marker object.

**The honest conclusion.** Least privilege is not free, and its cost is not
paid up front in careful design. It is paid in failures, one permission at a
time, each discovered by a run that got far enough to need it. Every one of
these could have been avoided with a wildcard policy, and every one of them was
worth hitting instead — but claiming the practice is costless would be false,
and the specific shape of the cost is: **you discover your permission boundary
by running into it, and delete and write paths are the last ones you exercise.**
