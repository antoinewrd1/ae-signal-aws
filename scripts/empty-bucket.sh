#!/usr/bin/env bash
# Empties a versioned S3 bucket, including delete markers.
#
# `aws s3 rm --recursive` does not empty a versioned bucket. It writes delete
# markers, which hide the current version while every prior version and every
# marker remains as a real object. The bucket lists as empty through the normal
# API and DeleteBucket still fails with BucketNotEmpty.
#
# Usage: ./scripts/empty-bucket.sh <bucket-name>
set -euo pipefail

BUCKET="${1:?usage: $0 <bucket-name>}"

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Bucket $BUCKET does not exist or is not accessible."
  exit 0
fi

echo "Emptying $BUCKET (versions and delete markers)..."

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || PY=".venv/bin/python"

"$PY" - "$BUCKET" <<'PYEOF'
import sys

import boto3

bucket = sys.argv[1]
s3 = boto3.client("s3")
deleted = 0

for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
    objects = [
        {"Key": o["Key"], "VersionId": o["VersionId"]}
        for key in ("Versions", "DeleteMarkers")
        for o in page.get(key, [])
    ]
    if objects:
        # delete_objects caps at 1000 per call; the paginator already
        # chunks below that.
        s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        deleted += len(objects)

print(f"Deleted {deleted} versions and delete markers.")
PYEOF

REMAINING=$(aws s3api list-object-versions --bucket "$BUCKET" \
  --query 'length(Versions || `[]`)' --output text)
MARKERS=$(aws s3api list-object-versions --bucket "$BUCKET" \
  --query 'length(DeleteMarkers || `[]`)' --output text)

echo "Remaining: $REMAINING versions, $MARKERS delete markers."
[ "$REMAINING" = "0" ] && [ "$MARKERS" = "0" ] && echo "Bucket is empty. Safe to destroy."
