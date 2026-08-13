#!/usr/bin/env bash
# One-time bootstrap: creates the S3 bucket that holds Terraform state.
# Chicken-and-egg problem - Terraform cannot create its own backend, so this
# runs once with the AWS CLI, then Terraform manages everything after it.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-ae-signal}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${PROJECT}-tfstate-${ACCOUNT_ID}"

echo "Account:  ${ACCOUNT_ID}"
echo "Region:   ${REGION}"
echo "Bucket:   ${BUCKET}"
echo

if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "Bucket already exists. Nothing to do."
else
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  echo "Bucket created."
fi

# Versioning lets you recover from a corrupted or truncated state file.
aws s3api put-bucket-versioning \
  --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

# State files contain resource metadata. Never public, no exceptions.
aws s3api put-public-access-block \
  --bucket "${BUCKET}" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

cat > infra/backend.hcl <<EOF
bucket = "${BUCKET}"
region = "${REGION}"
EOF

echo
echo "Wrote infra/backend.hcl"
echo "Next:  make tf-init"
