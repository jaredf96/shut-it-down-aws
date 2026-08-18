# Public demo hosting

Terraform for the static fixture demo: a **private** S3 bucket behind
CloudFront, reachable only through Origin Access Control.

```bash
cd deploy/terraform/demo
AWS_PROFILE=admin terraform init
AWS_PROFILE=admin terraform apply

# then publish the built demo
../../deploy-demo.sh admin
```

## Why it is shaped this way

**The bucket is not public.** A bucket policy trusts only this distribution
(matched on its ARN), and the public access block is fully on. A public-read
bucket would be fewer moving parts and the wrong habit to demonstrate in a
project about least privilege.

**No SPA fallback.** The app has no client-side routing, so rewriting every
403/404 to a `200 /index.html` would only turn a broken asset path into a page
that looks like it loaded. A missing file returns an error, as it should.

**Two cache policies, deliberately.** Vite fingerprints asset filenames, so
those are immutable for a year. `index.html` is not fingerprinted, so it is
`no-cache, must-revalidate` — cache it like an asset and a redeploy keeps
serving a stale page pointing at asset names that no longer exist. The deploy
script uploads them in separate passes for exactly this reason.

**Security headers** (HSTS, `X-Frame-Options: DENY`, `nosniff`,
`strict-origin-when-cross-origin`) are attached with a response headers policy
rather than baked into the app.

## Cost

Static files behind CloudFront's free tier: pennies. The stack includes an AWS
Budget as a guardrail against the unexpected — set `budget_alert_email` to get
notified at 80% of it, otherwise the budget tracks silently.

## Verifying a deploy

```bash
URL=$(terraform output -raw demo_url)
curl -sI "$URL/" | grep -i cache-control          # expect: no-cache
curl -s -o /dev/null -w '%{http_code}\n' \
  "https://$(terraform output -raw bucket_name).s3.amazonaws.com/index.html"
                                                  # expect: 403 (bucket private)
```

## Teardown

```bash
AWS_PROFILE=admin terraform destroy
```

The bucket is versioned, so `destroy` will refuse until object versions are
removed. Empty it first with
`aws s3 rm s3://<bucket> --recursive` plus a version purge, or delete the
versions from the console.
