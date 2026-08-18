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
