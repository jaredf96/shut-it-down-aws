output "demo_url" {
  description = "Public URL of the demo."
  value       = "https://${aws_cloudfront_distribution.canonical.domain_name}"
}

output "bucket_name" {
  description = "Origin bucket (private; readable only by the distribution)."
  value       = aws_s3_bucket.demo.id
}

output "distribution_id" {
  description = "CloudFront distribution id, needed to invalidate after a deploy."
  value       = aws_cloudfront_distribution.canonical.id
}

output "deploy_command" {
  description = "Rough equivalent of deploy/deploy-demo.sh; prefer the script, which uploads in two passes with the right cache headers."
  value       = <<-EOT
    npm --prefix frontend run build:demo
    aws s3 sync frontend/dist s3://${aws_s3_bucket.demo.id} --delete
    aws cloudfront create-invalidation \
      --distribution-id ${aws_cloudfront_distribution.canonical.id} --paths '/*'
  EOT
}
