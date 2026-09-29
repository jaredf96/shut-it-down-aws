# --- Canonical distribution ----------------------------------------------
#
# Serves the public demo, and is the distribution enrolled in the CloudFront
# Free flat-rate plan — which is what gives the demo a $0 ceiling with no
# overage billing.
#
# It was created outside Terraform by the CloudFront console wizard, together
# with its own Web ACL and OAC, and adopted here by import. The plan's
# subscription names this distribution's ARN specifically and cannot be moved to
# another one, so the plan is kept where it is rather than recreated.
#
# The README in this directory covers what the plan restricts — notably that a
# custom response headers policy is rejected outright.

data "aws_wafv2_web_acl" "plan" {
  name  = var.plan_web_acl_name
  scope = "CLOUDFRONT"
}

# The Free plan rejects a *custom* response headers policy but permits AWS's
# managed ones, so the security headers come from this rather than from
# aws_cloudfront_response_headers_policy.demo. Two deliberate differences from
# that custom policy: X-Frame-Options is SAMEORIGIN rather than DENY, and HSTS
# omits includeSubdomains — right for both hostnames the demo answers on: the
# subdomains of the shared *.cloudfront.net hostname are not ours to assert a
# policy for, and the custom domain (var.custom_domain) has none, so the
# directive would cover nothing.
data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

# The certificate for the custom domain. ACM issued it in us-east-1, the only
# region CloudFront reads certificates from, when the domain was attached in
# the console, DNS-validated by a CNAME at the registrar. The lookup is bound
# to the us-east-1 provider (main.tf) so var.region cannot redirect it. It is
# looked up rather than managed, so no apply or destroy here can delete it;
# ACM renews it by itself while that CNAME resolves (README § The custom
# domain).
data "aws_acm_certificate" "custom_domain" {
  provider    = aws.us_east_1
  count       = var.custom_domain == "" ? 0 : 1
  domain      = var.custom_domain
  statuses    = ["ISSUED"]
  most_recent = true
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

  # The custom domain was attached through the console on 2026-09-01. Carrying
  # it here is what stops an apply from removing it: without this line a
  # refreshed plan proposed dropping the alias and falling back to the
  # CloudFront-provided certificate.
  aliases = var.custom_domain == "" ? [] : [var.custom_domain]

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

  # Written to match the distribution as the console configured it: SNI and
  # TLSv1.2_2021 with the ACM certificate, or the CloudFront-provided
  # certificate when there is no custom domain.
  viewer_certificate {
    cloudfront_default_certificate = var.custom_domain == ""
    acm_certificate_arn            = var.custom_domain == "" ? null : data.aws_acm_certificate.custom_domain[0].arn
    ssl_support_method             = var.custom_domain == "" ? null : "sni-only"
    minimum_protocol_version       = var.custom_domain == "" ? null : "TLSv1.2_2021"
  }

  tags = {
    Name = "aws-cleanup"
  }
}
