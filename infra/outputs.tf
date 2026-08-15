output "account_id" {
  description = "AWS account this stack is deployed into."
  value       = local.account_id
}

output "region" {
  description = "Deployment region."
  value       = var.aws_region
}

output "name_prefix" {
  description = "Prefix applied to all resource names."
  value       = local.name_prefix
}

output "budget_name" {
  description = "Name of the monthly cost budget."
  value       = aws_budgets_budget.monthly.name
}

output "bronze_bucket" {
  description = "S3 bucket holding raw openFDA payloads."
  value       = aws_s3_bucket.bronze.id
}

output "extract_function_name" {
  description = "Name of the extractor Lambda."
  value       = aws_lambda_function.extract.function_name
}

output "extract_log_group" {
  description = "CloudWatch log group for the extractor."
  value       = aws_cloudwatch_log_group.extract.name
}

output "glue_job_name" {
  description = "Name of the transform job."
  value       = aws_glue_job.transform.name
}

output "glue_database" {
  description = "Glue Data Catalog database."
  value       = aws_glue_catalog_database.main.name
}

output "state_machine_arn" {
  description = "Step Functions pipeline."
  value       = aws_sfn_state_machine.pipeline.arn
}

output "alerts_topic_arn" {
  description = "SNS topic for pipeline failures. Confirm the email subscription."
  value       = aws_sns_topic.alerts.arn
}

output "enrich_function_name" {
  description = "Name of the enrichment Lambda."
  value       = aws_lambda_function.enrich.function_name
}
