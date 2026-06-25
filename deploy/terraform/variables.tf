variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "table_name" {
  description = "DynamoDB table name (matches DYNAMODB_TABLE_NAME)"
  type        = string
  default     = "cloud-lab-scans"
}
