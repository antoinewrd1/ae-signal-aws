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
