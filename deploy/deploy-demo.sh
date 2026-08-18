#!/usr/bin/env bash
# Build and publish the public fixture demo.
#
#   deploy/deploy-demo.sh [aws-profile]
#
# Two upload passes, because the caching rules differ:
#
#   * Vite fingerprints asset filenames (index-a1b2c3.js), so those are
#     immutable and can be cached for a year.
#   * index.html is NOT fingerprinted. If it were cached like the assets, a
#     redeploy would keep serving the old page — pointing at asset filenames
#     that no longer exist. It must revalidate every time.
#
# The CloudFront invalidation then clears edge copies of the short-lived files.
set -euo pipefail

PROFILE="${1:-admin}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/deploy/terraform/demo"

cd "$TF_DIR"
BUCKET="$(terraform output -raw bucket_name)"
DISTRIBUTION="$(terraform output -raw distribution_id)"
URL="$(terraform output -raw demo_url)"

echo "==> Building the demo profile (fixtures, no API client)"
npm --prefix "$ROOT/frontend" run build:demo

DIST="$ROOT/frontend/dist"
[ -f "$DIST/index.html" ] || { echo "build produced no index.html" >&2; exit 1; }

echo "==> Uploading fingerprinted assets (immutable, 1 year)"
aws s3 sync "$DIST" "s3://$BUCKET" \
  --profile "$PROFILE" \
  --delete \
  --exclude "index.html" \
  --exclude "*.map" \
  --cache-control "public, max-age=31536000, immutable"

echo "==> Uploading index.html (must revalidate)"
aws s3 cp "$DIST/index.html" "s3://$BUCKET/index.html" \
  --profile "$PROFILE" \
  --cache-control "no-cache, must-revalidate" \
  --content-type "text/html; charset=utf-8"

echo "==> Invalidating CloudFront"
aws cloudfront create-invalidation \
  --profile "$PROFILE" \
  --distribution-id "$DISTRIBUTION" \
  --paths '/*' \
  --query 'Invalidation.Id' --output text

echo
echo "Deployed: $URL"
echo "Edge propagation usually completes within a minute or two."
