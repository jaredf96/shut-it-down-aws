# Security

How Shut It Down handles credentials, permissions, mutating
actions, and money — and an honest list of what you'd harden before running it
as a real paid service.

## No hardcoded AWS keys

The app **never embeds AWS credentials** in code, config, or container images.
It relies entirely on the standard boto3 credential chain, resolved at runtime:

- A named profile / `~/.aws/credentials` (`aws configure`).
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional
  `AWS_SESSION_TOKEN`).
- An attached IAM role (ECS task role, Lambda execution role, EC2 instance
  profile) — the preferred path in production.

In Docker, credentials are **mounted read-only** (`~/.aws:/home/appuser/.aws:ro`)
rather than baked in (see [docker-compose.yml](../docker-compose.yml)), and the
`.dockerignore` excludes `.env` and `.aws`. The container also runs as a
non-root user.

API keys for the app's own auth are likewise never stored in plaintext — only a
**SHA-256 hash** of each key is persisted (`app/repositories/user_repository.py`).
The plaintext is shown once at creation and never again.

## Local profiles vs. assume-role

There are two credential modes, by design:

- **Single-account / local** — the app uses the server's own credentials
  (`app/aws/session.py: default_session`). Good for local dev and single-account
  deployments. Give those credentials a **read-only** policy.
- **Multi-account** — a tenant registers AWS accounts with a cross-account
  **role ARN**; the app calls `sts:AssumeRole` to get short-lived credentials per
  account (`session_for_account`). The app's own principal never holds standing
  access to customer accounts — only the ability to assume narrowly-scoped roles
  they explicitly grant, optionally with an `ExternalId`.

This separation means a customer onboards by creating a read-only role that
trusts your scanner, rather than handing over long-lived keys.

## Least-privilege IAM

Scanning needs only describe/list permissions. Attach the AWS-managed
`ReadOnlyAccess`, or this minimal policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:DescribeRegions", "ec2:DescribeInstances", "ec2:DescribeVolumes",
      "ec2:DescribeAddresses", "ec2:DescribeNatGateways",
      "elasticloadbalancing:DescribeLoadBalancers", "rds:DescribeDBInstances",
      "s3:ListAllMyBuckets", "s3:GetBucketLocation"
    ],
    "Resource": "*"
  }]
}
```

Grant the rest **only when you opt into the corresponding feature**:

| Feature | Extra permissions | Scope |
| --- | --- | --- |
| Persistence | `dynamodb:GetItem/PutItem/UpdateItem/DeleteItem/Query` (+ `CreateTable` for auto-create) | the app's table ARN |
| Multi-account | `sts:AssumeRole` | the registered role ARNs |
| Live pricing | `pricing:GetProducts` | `*` (Pricing API is global) |
| **Guided cleanup** | `ec2:StopInstances`, `ec2:ReleaseAddress`, `ec2:DeleteVolume` | only where cleanup is intended |

The cleanup write permissions are the **only** mutating actions the app can
take, and they map exactly to the three supported cleanup actions — nothing more.
The Terraform skeleton emits a least-privilege policy document
(`deploy/terraform/outputs.tf: app_policy_json`).

## Cleanup actions are disabled by default

The single mutating feature is **off unless explicitly enabled**, and even then
clears seven independent gates:

1. **Env flag** — without `ENABLE_CLEANUP_ACTIONS=true`, `POST /cleanup/execute`
   returns `403 "Cleanup actions are disabled in this environment."`
2. **Admin role** — members are rejected (`403`).
3. **Typed confirmation** — `confirm_resource_id` must equal `resource_id`.
4. **Dry-run by default** — the request body defaults `dry_run: true`; you must
   send `dry_run: false` to mutate.
5. **Target account ownership** — a request naming an `account_id` the tenant
   has not registered returns `404` and does nothing. The lookup is
   tenant-scoped, so this is not a cross-tenant boundary; what it prevents is
   the service falling back to its own default credentials and running the
   action against the host account while reporting success.
6. **Live precondition re-check** — state is verified against AWS at execution
   time and never trusts the client (an Elastic IP must still be unassociated; an
   EBS volume still unattached). Failing the check returns `409` and changes
   nothing.
7. **Audit** — every attempt is recorded (next section).

The action catalog is deliberately tiny and conservative: **Stop** EC2 (not
terminate), **release** unassociated Elastic IPs, **delete** unattached EBS
volumes. Terminating EC2 and deleting S3/RDS/NAT Gateways are **not automated**
and are surfaced under `not_supported` in `GET /cleanup/actions` for
transparency. There is **no bulk cleanup** — one resource per call.

## Audit logging

Every cleanup attempt — refused, failed, dry-run, or executed — produces an
audit entry (`app/repositories/audit_repository.py`,
`app/services/cleanup_service.py`) capturing **who** (tenant + user), **what**
(action, resource, region, account), the **outcome** (`success` / `dry_run` /
`confirmation_mismatch` / `unsupported_action` / `unknown_account` /
`precondition_failed` / `error`), a detail message, and a timestamp.

- Durable entries live in DynamoDB (`AUDIT#<tenant>`), tenant-scoped and
  time-sortable; `GET /cleanup/audit` lists them newest-first.
- The service **also** logs every attempt to the application logger, so there is
  a record even when persistence is disabled.

Because users are first-class (tenant + user id + role), every mutating action is
attributable to a specific user.

## Stripe webhook verification

Billing webhooks are **signature-verified** before they can change anything.
`POST /billing/webhook` reads the raw request body and the `Stripe-Signature`
header and calls `stripe.Webhook.construct_event(payload, signature, secret)`
(`app/services/billing_service.py: handle_webhook`). A bad or missing signature
raises, and the route returns `400` — no plan change occurs.

- The webhook secret comes from `STRIPE_WEBHOOK_SECRET` (env), never hardcoded.
- Only two event types mutate state: `checkout.session.completed` (→ Pro) and
  `customer.subscription.deleted` (→ Free); the tenant is resolved from the
  event's `client_reference_id` / `metadata.tenant_id`.
- Plan changes are server-authoritative. When Stripe is configured, the manual
  `POST /billing/plan` override is **disabled** (`409`) so plans can't be
  self-promoted client-side.

When Stripe is not configured, billing runs in a local/dev mode where an admin
sets the plan directly — useful for development, and clearly not for production.

## Production gaps

This is a portfolio-grade MVP. Before charging real customers, harden at least:

- **Tenant registration is open.** `POST /tenants` is gated only by an optional
  `ADMIN_TOKEN`. Add real sign-up, email verification, and rate limiting.
- **API keys, not sessions.** Auth is a single API key per user (hashed, but
  long-lived and not rotatable/expirable yet). Add key rotation/expiry, or move
  to OIDC/JWT sessions; consider per-key scopes.
- **No transport hardening in-app.** TLS, HSTS, security headers, and CORS lock-
  down are deployment concerns — the dev CORS config allows `localhost:5173`.
  Restrict origins and terminate TLS at the edge in production.
- **No rate limiting / abuse protection / WAF.** Scanning and cleanup endpoints
  should be throttled per tenant.
- **Audit log is append-only but not tamper-evident.** For compliance, ship
  audit events to an immutable store (e.g. CloudTrail Lake / S3 Object Lock).
- **Secrets in env.** Move `STRIPE_*`, SMTP creds, etc. to a secrets manager
  (AWS Secrets Manager / SSM) rather than plain environment variables.
- **Cleanup blast radius.** Even the safe actions are irreversible for EIP/EBS.
- **Outbound notifications are unthrottled.** There is no deduplication,
  cooldown, or send-rate limit, so a persistent finding re-alerts on every scan
  and a noisy account can flood a channel. Delivery is also synchronous: a slow
  or hanging SMTP server adds its timeout (up to ~10s) to the request.
- **`POST /notify` is not admin-gated.** It resolves the caller with
  `get_current_tenant`, so any authenticated member of a tenant can trigger
  outbound messages to that tenant's configured Slack/email channels. Whether
  sending should be admin-only is a product decision, deliberately left open —
  but it is an abuse vector worth closing before untrusted members exist.
  Consider soft-delete/snapshot-first, per-tenant allow-lists, and a second
  approver for destructive actions.
- **Billing edge cases.** Proration, failed payments
  (`invoice.payment_failed`), trials, and dunning aren't modeled — only
  upgrade/cancel.
- **Webhook idempotency & replay.** Persist processed Stripe event ids to ignore
  duplicates/replays.
- **Data lifecycle.** No retention/TTL on scans or audit entries; add DynamoDB
  TTL and a tenant data-deletion path for privacy requests.
- **Observability.** Add structured logging, metrics, tracing, and alerting on
  the service itself (not just on customer AWS resources).

See also: [ARCHITECTURE.md](ARCHITECTURE.md) and
[backend/README.md](../backend/README.md).
