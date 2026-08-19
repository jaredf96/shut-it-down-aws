# --- Canonical distribution (migration in progress) ----------------------
#
# E1QS09B3Q03DT4 was created by the CloudFront console wizard together with its
# own Web ACL, its own OAC, and the second bucket statement, and it is the
# distribution enrolled in the Free flat-rate plan — see the README in this
# directory. That plan is what gives the demo a $0 ceiling with no overage
# billing, and the subscription names this distribution's ARN specifically, so
# the plan cannot be moved onto the Terraform-created distribution.
#
# Hence the migration promotes this one to canonical and retires the other,
# rather than the other way round. Everything below is written to match what is
# already live, so that importing it proposes no surprises.

data "aws_wafv2_web_acl" "plan" {
  name  = var.plan_web_acl_name
  scope = "CLOUDFRONT"
}

# The Free plan rejects a *custom* response headers policy but permits AWS's
# managed ones, so the security headers come from this rather than from
# aws_cloudfront_response_headers_policy.demo. Two deliberate differences from
# that custom policy: X-Frame-Options is SAMEORIGIN rather than DENY, and HSTS
# omits includeSubdomains — which is the better choice on a shared
# *.cloudfront.net hostname in any case.
data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

# The console named this after the bucket, which embeds the account id, so the
# name is rebuilt from the bucket rather than pasted in literally.
resource "aws_cloudfront_origin_access_control" "canonical" {
  name                              = "oac-${local.bucket_name}.s3.us-east-1.amaz-mszqept7x18"
  description                       = "Created by CloudFront"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "canonical" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "Covers my shut it down AWS cleanup tool by preventing request spams and accruing high bills as a result."
  price_class         = "PriceClass_All"

  # Looked up, not passed in as a variable. This ACL is enrolled in the Free
  # plan's subscription, so the association must not be optional: a variable
  # defaulting to "" would let an unpopulated tfvars silently detach the WAF.
  web_acl_id = data.aws_wafv2_web_acl.plan.arn

  origin {
    domain_name              = aws_s3_bucket.demo.bucket_regional_domain_name
    origin_id                = "${aws_s3_bucket.demo.bucket_regional_domain_name}-mszqakmpv89"
    origin_access_control_id = aws_cloudfront_origin_access_control.canonical.id
  }

  default_cache_behavior {
    target_origin_id       = "${aws_s3_bucket.demo.bucket_regional_domain_name}-mszqakmpv89"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id

    # The console wizard created this distribution with no security headers at
    # all. See the data block above for why this is the managed policy.
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "aws-cleanup"
  }
}
