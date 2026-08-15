# GitHub Actions authentication via OIDC.
#
# The alternative is storing an access key as a repository secret. That key is
# long-lived, never expires on its own, and is readable by anything that can
# run a workflow. OIDC replaces it with a short-lived token GitHub mints per
# job and AWS exchanges for temporary credentials scoped to a role. Nothing
# durable is stored anywhere.

variable "github_repository" {
  description = "owner/repo allowed to assume the CI roles."
  type        = string
  default     = "antoinewrd1/ae-signal-aws"
}

variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider. Set false if the account already has one - it is account-wide and can only exist once."
  type        = bool
  default     = true
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

# --- Plan role: read-only, assumable from pull requests --------------------
#
# Pull requests can come from forks and from anyone with write access, so this
# role must not be able to change anything. It reads state and describes
# resources; that is all `terraform plan` needs.

resource "aws_iam_role" "ci_plan" {
  name = "${local.name_prefix}-ci-plan"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.oidc_provider_arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        # Scoped to pull requests from this repository only. Without the sub
        # condition, any GitHub repository in the world could assume this role.
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:pull_request"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ci_plan_readonly" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "ci_plan_state" {
  name = "${local.name_prefix}-ci-plan-state"
  role = aws_iam_role.ci_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      # Plan acquires the state lock, which is a write. Read-only access alone
      # is not sufficient.
      Sid    = "StateLock"
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        "arn:aws:s3:::${var.project_name}-tfstate-${local.account_id}",
        "arn:aws:s3:::${var.project_name}-tfstate-${local.account_id}/*"
      ]
    }]
  })
}

# --- Apply role: read-write, assumable only from main ----------------------

resource "aws_iam_role" "ci_apply" {
  name = "${local.name_prefix}-ci-apply"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.oidc_provider_arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # Exact match on the main branch ref. StringLike with a wildcard here
          # would let a branch named `main-anything` assume the apply role.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_apply" {
  name   = "${local.name_prefix}-ci-apply"
  role   = aws_iam_role.ci_apply.id
  policy = file("${path.module}/../iam/terraform-deployer-policy.json")
}
