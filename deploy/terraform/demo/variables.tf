variable "region" {
  description = "Region for the origin bucket. CloudFront itself is global."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "shut-it-down"
}

variable "monthly_budget_usd" {
  description = <<-EOT
    Budget ceiling for the demo. Hosting is a static site behind CloudFront's
    free tier, so real spend should be pennies — this exists to catch the
    unexpected (a scraper, a misconfiguration), not to track normal use.
  EOT
  type        = string
  default     = "5"
}

variable "budget_alert_email" {
  description = "Where to send the 80%-of-budget alert. Empty disables the notification."
  type        = string
  default     = ""
}

variable "plan_web_acl_name" {
  description = <<-EOT
    Name of the CLOUDFRONT-scope Web ACL that the pricing plan created and
    enrolled, which the canonical distribution attaches.

    Deliberately has no default. The name is generated per account when the plan
    is activated, so there is no sensible fallback, and an empty string would
    silently detach the WAF rather than fail. Kept out of version control
    because it is account-specific — see terraform.tfvars.example.
  EOT
  type        = string
}
