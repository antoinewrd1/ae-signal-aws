# Failure notification and observability.

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

# Unlike budget email subscribers, SNS subscriptions require the recipient to
# confirm via a link before anything is delivered. An unconfirmed subscription
# is silently useless, which is worth checking after the first apply.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failed" {
  alarm_name          = "${local.name_prefix}-pipeline-failed"
  alarm_description   = "Step Functions execution failed."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  # Without this, a period with no executions reports INSUFFICIENT_DATA and
  # the alarm oscillates. Missing data is not a failure.
  treat_missing_data = "notBreaching"

  dimensions    = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "enrich_errors" {
  alarm_name          = "${local.name_prefix}-enrich-errors"
  alarm_description   = "Enrichment Lambda erroring."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions    = { FunctionName = aws_lambda_function.enrich.function_name }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${local.name_prefix}-pipeline"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "Pipeline executions"
          region = var.aws_region
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", aws_sfn_state_machine.pipeline.arn],
            [".", "ExecutionsFailed", ".", "."],
            [".", "ExecutionsTimedOut", ".", "."]
          ]
          stat = "Sum", period = 300
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Execution duration"
          region = var.aws_region
          metrics = [
            ["AWS/States", "ExecutionTime", "StateMachineArn", aws_sfn_state_machine.pipeline.arn]
          ]
          stat = "Average", period = 300
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Lambda duration and errors"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.extract.function_name],
            [".", "Duration", ".", aws_lambda_function.enrich.function_name],
            [".", "Errors", ".", aws_lambda_function.enrich.function_name]
          ]
          stat = "Average", period = 300
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Bedrock token usage"
          region = var.aws_region
          metrics = [
            ["AWS/Bedrock", "InputTokenCount", "ModelId", var.bedrock_model_id],
            [".", "OutputTokenCount", ".", "."],
            [".", "InvocationClientErrors", ".", "."]
          ]
          stat = "Sum", period = 300
        }
      }
    ]
  })
}
