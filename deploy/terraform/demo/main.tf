# Public demo hosting: private S3 bucket behind CloudFront.
#
# The demo is a static build fed by fixtures — no credentials, no API client in
# the bundle — so the only thing this stack has to do is serve files safely.
#
# The bucket is NOT public. CloudFront reaches it through Origin Access Control
# and a bucket policy that trusts only this distribution, so the objects have
# exactly one path to the internet. A public-read bucket would be simpler and is
# the wrong habit to demonstrate in a project about least privilege.

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

  default_tags {
    tags = {
      Project   = "shut-it-down-aws"
      Component = "public-demo"
      ManagedBy = "terraform"
    }
  }
}

locals {
  bucket_name = "${var.name_prefix}-demo-${data.aws_caller_identity.current.account_id}"

  # The Free-plan distribution, created by the CloudFront console wizard and not
  # managed here yet. Its read grant is declared below so that a plan stops
  # trying to delete it — see the README in this directory. This local goes
  # away once the distribution itself is imported and can be referenced directly.
  plan_distribution_id = "E1QS09B3Q03DT4"
}

data "aws_caller_identity" "current" {}

# --- Origin bucket -------------------------------------------------------

resource "aws_s3_bucket" "demo" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "demo" {
  bucket                  = aws_s3_bucket.demo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "demo" {
  bucket = aws_s3_bucket.demo.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- CloudFront ----------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "demo" {
  name                              = "${var.name_prefix}-demo-oac"
  description                       = "OAC for the Shut It Down public demo"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "demo" {
  name = "${var.name_prefix}-demo-security-headers"

  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "demo" {
  # Kept disabled rather than deleted. Its bucket
  # grant was already removed, so it was serving 403; this stops it serving at
  # all. NOT deleted — deliberately kept so the cutover stays reversible. Set
  # back to true and apply to bring it back, then invalidate before reading any
  # status code as meaningful.
  enabled = false
  # Without this, a request for "/" maps to the bucket root. Origin Access
  # Control cannot list a bucket, so S3 answers 403 and the site looks broken
  # while every explicit path works fine.
  default_root_object = "index.html"
  comment             = "Shut It Down — public fixture demo"
  price_class         = "PriceClass_100" # NA + EU: cheapest that still feels fast

  origin {
    domain_name              = aws_s3_bucket.demo.bucket_regional_domain_name
    origin_id                = "s3-demo"
    origin_access_control_id = aws_cloudfront_origin_access_control.demo.id
  }

  default_cache_behavior {
    target_origin_id           = "s3-demo"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.demo.id
  }

  # Deliberately no SPA fallback. The app has no client-side routing, so there
  # are no deep links to rescue — and rewriting every 403/404 to a 200 index.html
  # would turn a broken asset path into a page that looks like it loaded. If
  # routing is added later, add the fallback then.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    # No custom domain yet, so use the CloudFront-provided certificate.
    cloudfront_default_certificate = true
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Only this distribution may read the bucket.
resource "aws_s3_bucket_policy" "demo" {
  bucket = aws_s3_bucket.demo.id
  policy = data.aws_iam_policy_document.demo_bucket.json
}

data "aws_iam_policy_document" "demo_bucket" {
  # E2V4IQWD851CWI's grant was removed here to cut it over — step one of its
  # retirement. It keeps serving whatever is still cached at the edge until an
  # invalidation clears it, so removing this alone does not prove the cut
  # landed; invalidate the distribution and wait before reading a 403 as
  # success. Restoring the statement and applying is the rollback.

  # The Free-plan distribution's grant, added by the console wizard and adopted
  # here so that a plan stops proposing to delete it. This is now the only path
  # from the bucket to the internet.
  statement {
    sid       = "AllowCloudFrontServicePrincipal"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.demo.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "AWS:SourceArn"
      values   = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${local.plan_distribution_id}"]
    }
  }
}

# --- Cost guardrail ------------------------------------------------------

resource "aws_budgets_budget" "demo" {
  name         = "${var.name_prefix}-demo-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = length(var.budget_alert_email) > 0 ? [1] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
