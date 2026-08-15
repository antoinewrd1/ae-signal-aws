# Extractor Lambda. The deployment package is source-only - the client uses
# nothing outside the standard library, so there is no pip build step, no
# layer, and no chance of local and deployed dependencies diverging.

data "archive_file" "extract" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/.build/extract.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

resource "aws_iam_role" "extract" {
  name = "${local.name_prefix}-extract"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Scoped to this bucket and to write-only on the data prefixes. The extractor
# has no reason to read anything back.
resource "aws_iam_role_policy" "extract" {
  name = "${local.name_prefix}-extract"
  role = aws_iam_role.extract.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteBronze"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.bronze.arn}/bronze/*"
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.extract.arn}:*"
      }
    ]
  })
}

# Declared explicitly rather than left to Lambda's implicit creation, so the
# retention period is set and logs do not accumulate forever.
resource "aws_cloudwatch_log_group" "extract" {
  name              = "/aws/lambda/${local.name_prefix}-extract"
  retention_in_days = 14
}

resource "aws_lambda_function" "extract" {
  function_name = "${local.name_prefix}-extract"
  role          = aws_iam_role.extract.arn
  handler       = "extract.handler.lambda_handler"
  runtime       = var.lambda_runtime
  architectures = ["arm64"]

  filename         = data.archive_file.extract.output_path
  source_code_hash = data.archive_file.extract.output_base64sha256

  # Generous because openFDA paginates slowly and backoff burns wall clock.
  timeout     = 300
  memory_size = 512

  environment {
    variables = {
      BRONZE_BUCKET          = aws_s3_bucket.bronze.id
      MAX_RECORDS_PER_WINDOW = tostring(var.max_records_per_window)
      LOG_LEVEL              = "INFO"
      OPENFDA_API_KEY        = var.openfda_api_key
    }
  }

  depends_on = [aws_cloudwatch_log_group.extract]
}

# Disabled by default. A forgotten schedule is the single most likely way this
# project generates an unexpected bill.
resource "aws_cloudwatch_event_rule" "extract_schedule" {
  name                = "${local.name_prefix}-extract-schedule"
  description         = "Daily openFDA extraction. Enable deliberately."
  schedule_expression = "cron(0 7 * * ? *)"
  state               = var.enable_schedule ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "extract" {
  rule      = aws_cloudwatch_event_rule.extract_schedule.name
  target_id = "extract-lambda"
  arn       = aws_lambda_function.extract.arn
  input     = jsonencode({ window_days = 7 })
}

resource "aws_lambda_permission" "events" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.extract.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.extract_schedule.arn
}

# ---------------------------------------------------------------------------
# Enrichment Lambda
#
# Unlike the extractor, this one has a third-party dependency with a compiled
# core (pydantic). Installing it with the developer's local pip produces wheels
# for the developer's platform, which then fail at import inside Lambda. The
# dependencies are therefore installed explicitly for the Lambda platform and
# Python version, not for whatever machine happens to run terraform.
# ---------------------------------------------------------------------------

resource "null_resource" "enrich_deps" {
  triggers = {
    requirements = filemd5("${path.module}/../src/enrich/requirements.txt")
    source_hash  = sha1(join("", [for f in fileset("${path.module}/../src", "**/*.py") : filesha1("${path.module}/../src/${f}")]))
    runtime      = var.lambda_runtime
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      BUILD="${path.module}/.build/enrich"
      rm -rf "$BUILD" && mkdir -p "$BUILD"
      pip install -r "${path.module}/../src/enrich/requirements.txt" \
        --target "$BUILD" \
        --platform manylinux2014_x86_64 \
        --python-version ${replace(var.lambda_runtime, "python", "")} \
        --only-binary=:all: \
        --quiet
      cp -r "${path.module}/../src" "$BUILD/src"
      find "$BUILD" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    EOT
  }
}

data "archive_file" "enrich" {
  type        = "zip"
  source_dir  = "${path.module}/.build/enrich"
  output_path = "${path.module}/.build/enrich.zip"
  depends_on  = [null_resource.enrich_deps]
}

resource "aws_iam_role" "enrich" {
  name = "${local.name_prefix}-enrich"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "enrich" {
  name              = "/aws/lambda/${local.name_prefix}-enrich"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "enrich" {
  name = "${local.name_prefix}-enrich"
  role = aws_iam_role.enrich.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadEnrichmentInput"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.bronze.arn, "${aws_s3_bucket.bronze.arn}/silver/*"]
      },
      {
        Sid      = "WriteGold"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.bronze.arn}/gold/*"
      },
      {
        Sid      = "InvokeBedrock"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.enrich.arn}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "enrich" {
  function_name = "${local.name_prefix}-enrich"
  role          = aws_iam_role.enrich.arn
  handler       = "src.enrich.handler.lambda_handler"
  runtime       = var.lambda_runtime

  # x86_64 rather than arm64: manylinux2014_x86_64 wheels are more reliably
  # published than aarch64 for the dependency set here. The cost difference is
  # noise at this volume.
  architectures = ["x86_64"]

  filename         = data.archive_file.enrich.output_path
  source_code_hash = data.archive_file.enrich.output_base64sha256

  # Bedrock calls run ~2s each and the batch is sequential.
  timeout     = 900
  memory_size = 512

  environment {
    variables = {
      BRONZE_BUCKET    = aws_s3_bucket.bronze.id
      BEDROCK_MODEL_ID = var.bedrock_model_id
      ENRICH_LIMIT     = tostring(var.enrich_limit)
      LOG_LEVEL        = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.enrich]
}
