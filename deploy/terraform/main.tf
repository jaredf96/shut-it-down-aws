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
data "aws_iam_policy_document" "app" {
  statement {
    sid     = "AppTableAccess"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
    ]
    resources = [aws_dynamodb_table.app.arn]
  }

  statement {
    sid       = "ReadOnlyScanning"
    actions   = [
      "ec2:Describe*",
      "elasticloadbalancing:DescribeLoadBalancers",
      "rds:DescribeDBInstances",
      "s3:ListAllMyBuckets",
      "s3:GetBucketLocation",
      "sts:AssumeRole",
    ]
    resources = ["*"]
  }
}
