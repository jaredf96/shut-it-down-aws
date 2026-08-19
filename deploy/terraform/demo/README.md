# Public demo hosting

Terraform for the static fixture demo: a **private** S3 bucket behind
CloudFront, reachable only through Origin Access Control.

```bash
cd deploy/terraform/demo
AWS_PROFILE=your-profile terraform init
AWS_PROFILE=your-profile terraform apply

# then publish the built demo
../../deploy-demo.sh your-profile
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

**Security headers** (HSTS, `X-Frame-Options`, `nosniff`,
`strict-origin-when-cross-origin`) are attached with a response headers policy
rather than baked into the app — specifically AWS's **managed**
`Managed-SecurityHeadersPolicy`, looked up as a data source.

That is not a style choice. **A distribution on the CloudFront Free plan cannot
carry a *custom* response headers policy** — AWS rejects the update with
`InvalidArgument: Distributions with the Free pricing plan can't have the
following features: Custom response headers policy`. Managed policies are
permitted. If you need a header the managed policy does not set, you cannot
simply write a custom policy; check the plan's feature table first.

The managed policy sets `X-Frame-Options: SAMEORIGIN` (not `DENY`) and omits
`includeSubdomains` on HSTS. The latter is the better choice here anyway: the
demo lives on a shared `*.cloudfront.net` hostname, so asserting a policy for
its subdomains is not ours to assert.

## The pricing plan is the cost control

The demo must have a **$0 ceiling with no overage billing**. Pay-as-you-go
CloudFront has no hard spend cap, so a traffic spike is an unbounded bill. The
distribution therefore sits on a CloudFront **Free flat-rate plan**: exceeding
its allowances degrades performance instead of charging.

The plan is a `pricingplanmanager` subscription enrolling **two** resources —
the distribution *and* a Web ACL. Consequences worth knowing before you change
anything:

- The enrolled Web ACL **cannot** be attached to a second distribution. AWS
  rejects it outright.
- The WAF entitlement covers *that* ACL, not WAF generally. Creating another
  Web ACL in Terraform would bill normally (~$5/month + $1/rule).
- The plan is not exposed by any API or by the AWS CLI. It is visible only in
  the CloudFront console, and in the CloudTrail record of its creation. Do not
  expect `terraform plan` to notice anything about it.
- The plan was created by a console wizard that also created the distribution,
  its OAC, its Web ACL, and a bucket-policy statement. It does not adopt
  existing resources.

The stack also includes an AWS Budget as a backstop — set `budget_alert_email`
to get notified at 80%, otherwise it tracks silently. The budget is an alert,
not a cap; the plan is what actually bounds spend.

## The disabled distribution

There are two distributions in the state. `aws_cloudfront_distribution.canonical`
serves the demo. `aws_cloudfront_distribution.demo` is an earlier
pay-as-you-go distribution, kept **disabled and undeleted** on purpose.

It has no bucket grant and `enabled = false`, so it serves nothing and its
hostname no longer resolves. It costs nothing. It exists as the cheapest
available rollback if the demo ever needs to leave the Free plan — recreating a
distribution is easy, but this one is already configured.

**The bucket policy is the kill switch.** It grants `s3:GetObject` to
CloudFront conditioned on a distribution ARN, one statement per distribution.
Removing a statement cuts that distribution off from the origin, reversibly, and
that is the intended way to cut one over. A plan that proposes dropping a
statement you did not mean to drop is a bug, not a tidy-up — check before
applying.

Removing the grant does **not** purge edge caches. CloudFront keeps serving
cached objects until they expire, and the fingerprinted assets are cached for a
year. Always invalidate and wait for `Completed`, then verify an **asset** path
and not just `/` — `index.html` is served `no-cache` and will revalidate
immediately, which makes the cut look complete when it is not.

## Two things that have actually bitten

**A failed apply can still write state.** Twice, an `UpdateDistribution` was
rejected by AWS and Terraform recorded the rejected value anyway, leaving state
claiming something AWS had refused. Nothing was wrong in AWS; the local state
was simply lying. Re-verify state after *any* errored apply, and repair with
`terraform apply -refresh-only`, which touches nothing in AWS.

The cheap detector is to run the plan both ways:

```bash
terraform plan
terraform plan -refresh=false
```

They should agree. When they disagree, state holds a value AWS never accepted —
a refreshed plan hides it, and a `-refresh=false` plan acts on it.

**Disabling a distribution withdraws its DNS.** The hostname stops resolving
entirely, so a check against it fails to connect rather than returning a status
code. Do not read a connection error as evidence about the bucket policy; those
are separate cuts, and re-enabling has to wait for DNS as well as for the
distribution to redeploy.

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
AWS_PROFILE=your-profile terraform destroy
```

The bucket is versioned, so `destroy` will refuse until object versions are
removed. Empty it first with
`aws s3 rm s3://<bucket> --recursive` plus a version purge, or delete the
versions from the console.

Note that `destroy` now targets the Free-plan distribution too, since it is
managed here. The versioned bucket happens to block it, but treat that as an
accident rather than a safety net.
