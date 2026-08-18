output "demo_url" {
  description = "Public URL of the demo."
  value       = "https://${aws_cloudfront_distribution.demo.domain_name}"
}

output "bucket_name" {
  description = "Origin bucket (private; readable only by the distribution)."
  value       = aws_s3_bucket.demo.id
}

output "distribution_id" {
  description = "CloudFront distribution id, needed to invalidate after a deploy."
  value       = aws_cloudfront_distribution.demo.id
}

output "deploy_command" {
  description = "Copy the built demo up and invalidate the cache."
  value       = <<-EOT
    npm --prefix frontend run build:demo
    aws s3 sync frontend/dist s3://${aws_s3_bucket.demo.id} --delete
    aws cloudfront create-invalidation \
      --distribution-id ${aws_cloudfront_distribution.demo.id} --paths '/*'
  EOT
}
