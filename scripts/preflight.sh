#!/usr/bin/env bash
# Verifies every precondition for Step 1 before you run terraform.
# Safe to re-run. Makes no changes and creates no billable resources
# (the Bedrock check is a read-only list call).
set -uo pipefail

PASS=0
FAIL=0
WARN=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; WARN=$((WARN+1)); }

# Compare dotted versions: returns 0 if $1 >= $2
vge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }

echo
echo "== Tooling =="

if command -v aws >/dev/null 2>&1; then
  V=$(aws --version 2>&1 | sed -n 's|aws-cli/\([0-9.]*\).*|\1|p')
  case "$V" in
    2.*) ok "aws-cli $V" ;;
    *)   bad "aws-cli $V — v2 required. v1 lacks the bedrock commands." ;;
  esac
else
  bad "aws-cli not found"
fi

if command -v terraform >/dev/null 2>&1; then
  V=$(terraform version -json 2>/dev/null | sed -n 's/.*"terraform_version": *"\([^"]*\)".*/\1/p')
  [ -z "$V" ] && V=$(terraform version | head -1 | sed 's/Terraform v//')
  if vge "$V" "1.10.0"; then ok "terraform $V"
  else bad "terraform $V — need >= 1.10 for S3 backend use_lockfile"; fi
else
  bad "terraform not found"
fi

if command -v python3 >/dev/null 2>&1; then
  V=$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')
  if vge "$V" "3.11.0"; then ok "python $V"
  else bad "python $V — need >= 3.11"; fi
else
  bad "python3 not found"
fi

for t in git make docker; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t present"; else bad "$t not found"; fi
done

if command -v gh >/dev/null 2>&1; then ok "gh present"
else warn "gh not found — optional, only used to create the remote repo"; fi

echo
echo "== Repo =="

if [ -f Makefile ] && [ -d infra ]; then
  ok "running from repo root"
else
  bad "not in the repo root — cd into ae-signal-aws first"
fi

if [ -d .git ]; then ok "git initialized"; else warn "git not initialized — run: git init && git branch -M main"; fi

if [ -f infra/terraform.tfvars ]; then
  grep -q 'you@example.com' infra/terraform.tfvars \
    && bad "infra/terraform.tfvars still has the placeholder email" \
    || ok "infra/terraform.tfvars configured"
else
  bad "infra/terraform.tfvars missing — cp infra/terraform.tfvars.example infra/terraform.tfvars"
fi

if [ -f infra/backend.hcl ]; then ok "infra/backend.hcl present"
else warn "infra/backend.hcl missing — run ./scripts/bootstrap-backend.sh"; fi

if git rev-parse --git-dir >/dev/null 2>&1; then
  if git ls-files --error-unmatch infra/terraform.tfvars >/dev/null 2>&1; then
    bad "terraform.tfvars is TRACKED BY GIT — untrack it before committing"
  else
    ok "terraform.tfvars not tracked by git"
  fi
fi

echo
echo "== AWS credentials =="

CALLER=$(aws sts get-caller-identity --output json 2>/dev/null)
if [ -n "$CALLER" ]; then
  ARN=$(echo "$CALLER" | sed -n 's/.*"Arn": *"\([^"]*\)".*/\1/p')
  ok "authenticated as $ARN"
  case "$ARN" in
    *":root") warn "you are using ROOT credentials — switch to the ae-signal-deployer user" ;;
    *"ae-signal-deployer") ok "using the project deployer user" ;;
  esac
  echo "$CALLER" | grep -q '"Account"' && \
    ok "account $(echo "$CALLER" | sed -n 's/.*"Account": *"\([^"]*\)".*/\1/p')"
else
  bad "aws sts get-caller-identity failed — credentials not configured"
fi

REGION=$(aws configure get region 2>/dev/null || true)
[ -z "$REGION" ] && REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [ "$REGION" = "us-east-1" ]; then ok "region us-east-1"
elif [ -n "$REGION" ]; then warn "region is $REGION — scaffold defaults to us-east-1; keep them consistent"
else bad "no default region set — run: aws configure set region us-east-1"; fi

[ -n "${AWS_PROFILE:-}" ] && ok "AWS_PROFILE=$AWS_PROFILE" || warn "AWS_PROFILE not exported"

echo
echo "== Bedrock =="

MODELS=$(aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic \
  --query "modelSummaries[?modelLifecycle.status=='ACTIVE'].modelId" --output text 2>/dev/null)
if [ -n "$MODELS" ]; then
  ok "bedrock reachable"
  HAIKU=$(echo "$MODELS" | tr '\t' '\n' | grep -i haiku | tail -1)
  if [ -n "$HAIKU" ]; then
    ok "active haiku model: $HAIKU"
    echo "        try:  us.$HAIKU   (cross-region inference profile)"
  else
    warn "no active haiku model found; active anthropic models:"
    echo "$MODELS" | tr '\t' '\n' | sed 's/^/        /'
  fi
else
  bad "cannot list bedrock models — check credentials, region, and bedrock:ListFoundationModels permission"
fi

echo
echo "== Summary =="
printf '  %d passed, %d warnings, %d failed\n\n' "$PASS" "$WARN" "$FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "  Fix the failures above before running: make tf-apply"
  exit 1
fi
echo "  Ready. Next: make tf-init && make tf-plan"
