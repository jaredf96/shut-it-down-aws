# Minimal infrastructure skeleton for Shut It Down.
#
# This provisions the single DynamoDB table the app uses. It is a STARTING
# POINT — extend it with the Lambda function (container image), API Gateway /
# Function URL, and IAM role for your hosted deployment.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# Single-table design: pk (HASH) + sk (RANGE), on-demand billing.
resource "aws_dynamodb_table" "app" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Project = "shut-it-down-aws"
  }
}

# Least-privilege policy document the app's runtime role should attach.
# (Scanning uses read-only AWS APIs; persistence uses this table.)
#
# This is the same grant deploy/cloudformation/platform-role.yaml creates, for
# operators who have no runtime role yet. Keep the two in step — the actions
# below are pinned against docs/SECURITY.md by
# backend/tests/test_platform_role_template.py.
data "aws_iam_policy_document" "app" {
  statement {
    sid     = "AppTableAccess"
    actions = [
      # /ready calls DescribeTable on every probe; without it the backend
      # reports itself unready while history reads and writes work.
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
    ]
    resources = [aws_dynamodb_table.app.arn]
  }

  # Exactly the nine actions published in docs/SECURITY.md § Least-privilege
  # IAM. This used to say "ec2:Describe*", which quietly granted more than the
  # document promised -- DescribeInstanceAttribute reads instance user data.
  statement {
    sid = "ReadOnlyScanning"
    actions = [
      "ec2:DescribeRegions",
      "ec2:DescribeInstances",
      "ec2:DescribeVolumes",
      "ec2:DescribeAddresses",
      "ec2:DescribeNatGateways",
      "elasticloadbalancing:DescribeLoadBalancers",
      "rds:DescribeDBInstances",
      "s3:ListAllMyBuckets",
      "s3:GetBucketLocation",
    ]
    resources = ["*"]
  }

  # Registered target ARNs are not knowable here: onboarding is self-service and
  # the scanner role's name is overridable. Scope by the tag scanner-role.yaml
  # puts on every role it creates, so a role that merely happens to trust this
  # one is not assumable. The tag is a namespace guard, not an authorization
  # boundary -- the target's trust policy plus external ID remains that.
  statement {
    sid       = "AssumeRegisteredScannerRoles"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = ["shut-it-down-aws"]
    }
  }
}
