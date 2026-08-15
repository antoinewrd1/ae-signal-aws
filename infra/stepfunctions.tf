# Orchestration. Chains extract -> transform -> quality gate -> enrich, with
# retries on transient failures and a catch-all that notifies rather than
# failing silently.

resource "aws_iam_role" "sfn" {
  name = "${local.name_prefix}-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  name = "${local.name_prefix}-sfn"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeLambdas"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.extract.arn, aws_lambda_function.enrich.arn]
      },
      {
        Sid      = "RunGlueJob"
        Effect   = "Allow"
        Action   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
        Resource = "*"
      },
      {
        Sid      = "Notify"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      },
      {
        # Required for the .sync integration pattern: Step Functions polls the
        # Glue run via EventBridge managed rules, which it creates itself.
        Sid      = "SyncIntegrationSupport"
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "*"
      },
      {
        Sid    = "Logging"
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.name_prefix}-pipeline"
  retention_in_days = 14
}

locals {
  # Transient infrastructure failures. Applied to every task.
  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException", "Lambda.AWSLambdaException",
      "Lambda.SdkClientException", "Lambda.TooManyRequestsException"
    ]
    IntervalSeconds = 2
    MaxAttempts     = 3
    BackoffRate     = 2.0
  }]
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment = "openFDA ingest, transform, quality gate, enrich"
    StartAt = "Extract"
    States = {
      Extract = {
        Type       = "Task"
        Resource   = "arn:aws:states:::lambda:invoke"
        Parameters = { FunctionName = aws_lambda_function.extract.arn, "Payload.$" = "$" }
        ResultSelector = {
          "record_count.$" = "$.Payload.record_count"
          "run_id.$"       = "$.Payload.run_id"
          "status.$"       = "$.Payload.status"
        }
        ResultPath = "$.extract"
        Retry      = local.lambda_retry
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "NotifyFailure" }]
        Next       = "AnyRecords"
      }

      # Quality gate. Running Glue on an empty bronze prefix costs the same
      # 10-minute minimum as running it on real data and produces nothing.
      AnyRecords = {
        Type = "Choice"
        Choices = [{
          Variable           = "$.extract.record_count"
          NumericGreaterThan = 0
          Next               = "Transform"
        }]
        Default = "NoNewData"
      }

      NoNewData = {
        Type    = "Succeed"
        Comment = "Extract returned zero records. Nothing downstream to do."
      }

      Transform = {
        Type = "Task"
        # .sync blocks until the Glue run reaches a terminal state, so a
        # failed transform stops the pipeline instead of letting enrichment
        # run against stale silver data.
        Resource   = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = { JobName = aws_glue_job.transform.name }
        ResultPath = "$.transform"
        Retry = [{
          ErrorEquals     = ["Glue.ConcurrentRunsExceededException"]
          IntervalSeconds = 30
          MaxAttempts     = 2
          BackoffRate     = 2.0
        }]
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "NotifyFailure" }]
        Next  = "Enrich"
      }

      Enrich = {
        Type       = "Task"
        Resource   = "arn:aws:states:::lambda:invoke"
        Parameters = { FunctionName = aws_lambda_function.enrich.arn, Payload = { "limit.$" = "$.limit" } }
        ResultSelector = {
          "attempted.$"     = "$.Payload.attempted"
          "enriched.$"      = "$.Payload.enriched"
          "dead_lettered.$" = "$.Payload.dead_lettered"
          "success_rate.$"  = "$.Payload.success_rate"
          "cost_usd.$"      = "$.Payload.estimated_cost_usd"
        }
        ResultPath = "$.enrich"
        Retry      = local.lambda_retry
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "NotifyFailure" }]
        Next       = "Done"
      }

      Done = { Type = "Succeed" }

      NotifyFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = aws_sns_topic.alerts.arn
          Subject     = "ae-signal pipeline failed"
          "Message.$" = "States.JsonToString($)"
        }
        # Fail after notifying, so the execution is recorded as failed and the
        # ExecutionsFailed alarm fires. Succeeding here would hide the failure.
        Next = "Failed"
      }

      Failed = { Type = "Fail", Error = "PipelineFailed", Cause = "See SNS notification" }
    }
  })
}
