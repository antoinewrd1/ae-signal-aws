# Glue transform job. Spark logic is developed and tested locally; Glue runs
# are counted, not scheduled. Glue bills a 10-minute minimum per run, so this
# is the one component where a forgotten trigger actually costs money.

resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.bronze.id
  key    = "scripts/transform_job.py"
  source = "${path.module}/../src/transform/job.py"
  etag   = filemd5("${path.module}/../src/transform/job.py")
}

data "archive_file" "transform_module" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/.build/transform.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

resource "aws_s3_object" "glue_module" {
  bucket = aws_s3_bucket.bronze.id
  key    = "scripts/transform.zip"
  source = data.archive_file.transform_module.output_path
  etag   = data.archive_file.transform_module.output_md5
}

resource "aws_iam_role" "glue" {
  name = "${local.name_prefix}-glue"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_data" {
  name = "${local.name_prefix}-glue-data"
  role = aws_iam_role.glue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadBronzeAndScripts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.bronze.arn, "${aws_s3_bucket.bronze.arn}/*"]
      },
      {
        Sid      = "WriteSilverGold"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.bronze.arn}/silver/*", "${aws_s3_bucket.bronze.arn}/gold/*"]
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws-glue/*"
      }
    ]
  })
}

resource "aws_glue_catalog_database" "main" {
  name        = replace("${local.name_prefix}", "-", "_")
  description = "openFDA adverse event medallion layers"
}

resource "aws_glue_job" "transform" {
  name         = "${local.name_prefix}-transform"
  role_arn     = aws_iam_role.glue.arn
  glue_version = var.glue_version

  # G.1X is the smallest worker. Two of them is the practical minimum and is
  # ample for this data volume - larger workers would cost more and finish no
  # sooner on a dataset this size.
  worker_type       = "G.1X"
  number_of_workers = 2

  # Hard stop. Without it, a hung job bills until Glue's default timeout.
  timeout = 15

  # No retries: a failed quality gate is deterministic, and retrying it just
  # pays twice to fail the same way.
  max_retries = 0

  command {
    script_location = "s3://${aws_s3_bucket.bronze.id}/${aws_s3_object.glue_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--extra-py-files"                   = "s3://${aws_s3_bucket.bronze.id}/${aws_s3_object.glue_module.key}"
    "--bronze_path"                      = "s3://${aws_s3_bucket.bronze.id}/bronze/drug_event/"
    "--silver_path"                      = "s3://${aws_s3_bucket.bronze.id}/silver"
    "--gold_path"                        = "s3://${aws_s3_bucket.bronze.id}/gold"
    "--job-language"                     = "python"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-spark-ui"                  = "false"
    "--TempDir"                          = "s3://${aws_s3_bucket.bronze.id}/glue-temp/"
  }
}
