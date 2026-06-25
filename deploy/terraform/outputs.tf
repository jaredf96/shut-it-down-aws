output "table_name" {
  description = "DynamoDB table name — set as DYNAMODB_TABLE_NAME on the backend"
  value       = aws_dynamodb_table.app.name
}

output "table_arn" {
  value = aws_dynamodb_table.app.arn
}

output "app_policy_json" {
  description = "IAM policy document to attach to the backend's runtime role"
  value       = data.aws_iam_policy_document.app.json
}
