# Bronze layer. Raw openFDA payloads land here unmodified so the pipeline can
# always be replayed from source.

resource "aws_s3_bucket" "bronze" {
  bucket = "${local.name_prefix}-bronze-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    # Cuts KMS/S3 request costs on high-object-count prefixes.
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "bronze" {
  bucket                  = aws_s3_bucket.bronze.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  bucket     = aws_s3_bucket.bronze.id
  depends_on = [aws_s3_bucket_versioning.bronze]

  # Raw data expires after 90 days. Manifests are small and kept indefinitely
  # so the run history outlives the data it describes.
  rule {
    id     = "expire-raw-data"
    status = "Enabled"
    filter {
      prefix = "bronze/drug_event/"
    }
    expiration {
      days = 90
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }

  # Versioning plus interrupted multipart uploads is a classic way to pay for
  # storage you cannot see in the console.
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }
}
