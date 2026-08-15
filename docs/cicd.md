# CI/CD

## Two workflows, deliberately separated

**`ci.yml`** — lint, unit tests, `terraform validate`. Runs on every push and
pull request. **Holds no AWS credentials at all.** Every test mocks its
dependencies (moto for S3, patched clients for Bedrock and openFDA), and
`terraform init -backend=false` validates syntax without touching state. This
means a pull request from a fork can run the full suite safely.

**`terraform.yml`** — plan on pull requests, apply on main. Needs AWS access,
so it is kept separate and authenticates via OIDC.

Splitting them matters: if credentials lived in the same workflow as the test
job, every test run would carry access it does not need.

## No stored AWS keys

The obvious approach is an access key in repository secrets. That key is
long-lived, does not rotate, and is available to anything that can trigger a
workflow — including a malicious pull request if the workflow is misconfigured.

GitHub OIDC replaces it. GitHub mints a short-lived signed token per job; AWS
verifies it against the registered provider and exchanges it for temporary
credentials. Nothing durable is stored, and revoking access means deleting a
role rather than hunting for a leaked key.

## Two roles, not one

| Role | Assumable from | Permissions |
|---|---|---|
| `ae-signal-dev-ci-plan` | pull requests only | `ReadOnlyAccess` + state lock |
| `ae-signal-dev-ci-apply` | `refs/heads/main` only | full deployer policy |

A pull request must not be able to change infrastructure regardless of who
opened it, so the plan role cannot write. The apply role is reachable only
from the main branch.

The trust conditions are the security boundary and are easy to get subtly
wrong:

- The `sub` condition is mandatory. Without it, **any** GitHub repository can
  assume the role. The `aud` check alone is not a restriction.
- The apply role uses `StringEquals` on the exact ref, not `StringLike`. A
  wildcard such as `repo:owner/repo:ref:refs/heads/main*` would also match a
  branch named `main-experiment`, which anyone with write access can create.

## Required repository configuration

Terraform outputs the values; set them as **repository variables** (not
secrets — role ARNs are not sensitive), under Settings → Secrets and variables
→ Actions → Variables:

| Variable | Source |
|---|---|
| `AWS_PLAN_ROLE_ARN` | `terraform output ci_plan_role_arn` |
| `AWS_APPLY_ROLE_ARN` | `terraform output ci_apply_role_arn` |
| `TF_STATE_BUCKET` | the bucket from `infra/backend.hcl` |
| `ALERT_EMAIL` | the address used in `terraform.tfvars` |

Then create a `production` environment under Settings → Environments and add
yourself as a required reviewer. Apply then pauses for approval rather than
running on merge.

## Bootstrapping order

The OIDC roles are defined in the same Terraform configuration they authorise,
so the first apply must run locally with the deployer user. After that,
`terraform.yml` can manage the stack — including the roles themselves.

## Known limitations

- The apply role uses the same broad policy as the local deployer rather than
  a narrower CI-specific one.
- Plan output is posted as a new PR comment each run rather than updating one,
  so a long-lived branch accumulates comments.
- No drift detection. A scheduled `terraform plan` reporting unexpected
  differences would catch console changes.
