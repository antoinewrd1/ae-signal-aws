terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State bucket is created once by scripts/bootstrap-backend.sh before
  # the first `terraform init`. use_lockfile replaces the old DynamoDB
  # lock table and requires Terraform >= 1.10.
  backend "s3" {
    key          = "ae-signal/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
    # bucket and region are supplied via backend.hcl (git-ignored)
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Owner       = var.owner
      Repo        = "github.com/antoinewrd1/ae-signal-aws"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  name_prefix = "${var.project_name}-${var.environment}"
}
