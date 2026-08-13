variable "project_name" {
  description = "Short project slug used as a prefix for all resource names."
  type        = string
  default     = "ae-signal"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project_name))
    error_message = "project_name must be lowercase alphanumeric with hyphens, 3-20 chars."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region. us-east-1 has the widest Bedrock model availability."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Tag value identifying the resource owner."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives budget and pipeline failure alerts."
  type        = string

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "monthly_budget_usd" {
  description = "Hard ceiling for monthly spend. Alerts fire well below this."
  type        = number
  default     = 25
}

variable "lambda_runtime" {
  description = "Lambda Python runtime. Pin deliberately - your local Python may be newer than any available runtime."
  type        = string
  default     = "python3.13"
}

variable "max_records_per_window" {
  description = "Cap on records pulled per date window. Keeps runs inside the openFDA quota."
  type        = number
  default     = 500
}

variable "openfda_api_key" {
  description = "Optional openFDA API key. Raises the daily quota from 1,000 to 120,000 requests."
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_schedule" {
  description = "Enable the daily EventBridge trigger. Leave false unless actively running the pipeline."
  type        = bool
  default     = false
}
