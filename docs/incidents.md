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

## request_count silently reported zero

**Symptom** — Every run manifest reported `request_count: 0` while the
extractor was demonstrably making API calls.

**Impact** — No pipeline failure. The manifest simply carried a wrong value,
which is worse: quota consumption was unmeasurable and nothing signalled it.

**Root cause** — The field was declared on the RunManifest dataclass before
the code that populates it was written, and no test asserted on it. Unit
tests all mocked `OpenFDAClient._get`, which is the exact method the counter
lives inside, so the counter never executed under test.

**Fix** — Increment in `_get` on every attempt (retries consume quota too),
and assign `client.request_count` to the manifest in both the success and
failure paths.

**Prevention** — Added a test that mocks at the `urllib.request.urlopen`
boundary rather than at `_get`, so the counted code path actually runs.
