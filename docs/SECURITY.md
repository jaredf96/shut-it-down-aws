# Security

How Shut It Down handles credentials, permissions, and mutating actions — and an
honest list of what you'd harden before pointing it at AWS accounts you care
about.

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
- **Multi-account** — a workspace registers AWS accounts with a cross-account
  **role ARN**; the app calls `sts:AssumeRole` to get short-lived credentials per
  account (`session_for_account`). The app's own principal never holds standing
  access to the scanned accounts — only the ability to assume narrowly-scoped
  roles they explicitly grant, with an `ExternalId`. The API treats the external
  ID as optional, for manually-configured roles; the onboarding template below
  requires one.

This separation means a student's lab account is onboarded by creating a
read-only role that trusts the scanner, rather than handing over long-lived keys.

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
They belong to the **platform's own** runtime role: the Terraform skeleton emits
that policy document (`deploy/terraform/outputs.tf: app_policy_json`).

The policy above is the other one — what a **scanned** account grants. It is what
`deploy/cloudformation/scanner-role.yaml` creates, and
`backend/tests/test_onboarding_template.py` parses both this document and that
template to assert they still say the same thing. A permission added to one and
not the other fails the test rather than quietly widening the grant.

## Onboarding an account

An instructor onboards each lab account by having its owner run one
CloudFormation stack. Nobody hands over keys, and the platform never holds
standing access.

**The order is forced by the external ID.** The stack takes it as a parameter, so
it has to exist before the role does — and the role ARN the platform registers
does not exist until the stack has run:

```bash
make onboarding-id      # 1. generate the external ID. One per account, never reused.
```

```bash
# 2. The account owner deploys the role, with the ID and your backend's role ARN.
aws cloudformation deploy \
  --template-file deploy/cloudformation/scanner-role.yaml \
  --stack-name shut-it-down-onboarding \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      PlatformRoleArn=arn:aws:iam::<PLATFORM_ACCOUNT>:role/<BACKEND_ROLE> \
      ExternalId=<THE_GENERATED_ID>
```

3. Register the stack's `RoleArn` output in the dashboard (**Accounts → Add
   account**) with **the same external ID**. Scans fan out to it from then on.

**`PlatformRoleArn` is the backend's own role, not the account root.** The
template rejects a root ARN outright. An account-root principal delegates the
trust to every principal in that account, which is a much wider grant than "the
one role my scanner runs as" — and the external ID does not narrow it back down.

**What the external ID is for.** It is confused-deputy protection: it stops
someone from persuading the platform to assume a role on their behalf. It is
**not** a secret that makes a role ARN safe to publish, and knowing a role ARN
never granted anyone the right to assume it.

**What this does not guarantee.** The external ID is generated by the operator,
so the platform does not enforce uniqueness, non-reuse, or expiry, and cannot
prove a submitted value came from `make onboarding-id`. That is a recorded
decision with revisit triggers, not an oversight — see `docs/DECISIONS.md` D6.

## Cleanup actions are disabled by default

The single mutating feature is **off unless explicitly enabled**, and even then
clears seven independent gates:

1. **Env flag** — without `ENABLE_CLEANUP_ACTIONS=true`, `POST /cleanup/execute`
   returns `403 "Cleanup actions are disabled in this environment."`
2. **Admin role** — members are rejected (`403`).
3. **Typed confirmation** — `confirm_resource_id` must equal `resource_id`.
4. **Dry-run by default** — the request body defaults `dry_run: true`; you must
   send `dry_run: false` to mutate.
5. **Target account ownership** — a request naming an `account_id` the workspace
   has not registered returns `404` and does nothing. The lookup is
   workspace-scoped, so this is not a cross-workspace boundary; what it prevents is
   the service falling back to its own default credentials and running the
   action against the host account while reporting success.

   Omitting `account_id` remains a valid request meaning "use the server's own
   credentials", so the gate cannot close the case on its own — the service is
   handed a resource id and a region, and no lookup tells it which account that
   id lives in. The dashboard therefore sends the account of the finding it is
   acting on, and shows it in the form (`frontend/src/components/CleanupPanel.jsx`).
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
`app/services/cleanup_service.py`) capturing **who** (workspace + user), **what**
(action, resource, region, account), the **outcome** (`success` / `dry_run` /
`confirmation_mismatch` / `unsupported_action` / `unknown_account` /
`precondition_failed` / `error`), a detail message, and a timestamp.

- Durable entries live in DynamoDB (`AUDIT#<workspace>`), workspace-scoped and
  time-sortable; `GET /cleanup/audit` lists them newest-first.
- The service **also** logs every attempt to the application logger, so there is
  a record even when persistence is disabled.

Because users are first-class (workspace + user id + role), every mutating action is
attributable to a specific user.

## Production gaps

Shut It Down is self-hosted and exposes no public multi-tenant API (D1), so the
gaps that mattered for a SaaS front door — open registration, per-customer abuse
protection — no longer apply. What remains is what an operator pointing this at
real AWS accounts should still know: credentials, blast radius, and the trail
you would want afterwards.

- **API keys, not sessions.** Auth is a single API key per user (hashed, but
  long-lived and not rotatable/expirable yet). Add key rotation/expiry, or move
  to OIDC/JWT sessions; consider per-key scopes.
- **No transport hardening in-app.** TLS, HSTS, security headers, and CORS lock-
  down are deployment concerns — the dev CORS config allows `localhost:5173`.
  Restrict origins and terminate TLS at the edge in production.
- **Audit log is append-only but not tamper-evident.** For compliance, ship
  audit events to an immutable store (e.g. CloudTrail Lake / S3 Object Lock).
- **Secrets in env.** Move SMTP credentials and anything else sensitive to a
  secrets manager (AWS Secrets Manager / SSM) rather than plain environment
  variables.
- **Cleanup blast radius.** Even the safe actions are irreversible for EIP/EBS.
- **Outbound notifications are unthrottled.** There is no deduplication,
  cooldown, or send-rate limit, so a persistent finding re-alerts on every scan
  and a noisy account can flood a channel. Delivery is also synchronous: a slow
  or hanging SMTP server adds its timeout (up to ~10s) to the request.
- **`POST /notify` is not admin-gated.** It resolves the caller with
  `get_current_workspace`, so any authenticated member of a workspace can trigger
  outbound messages to that workspace's configured Slack/email channels. Whether
  sending should be admin-only is a product decision, deliberately left open —
  but it is an abuse vector worth closing before untrusted members exist.
  Consider soft-delete/snapshot-first, per-workspace allow-lists, and a second
  approver for destructive actions.
- **Data lifecycle.** No retention/TTL on scans or audit entries; add DynamoDB
  TTL and a workspace data-deletion path.
- **Observability.** Add structured logging, metrics, tracing, and alerting on
  the service itself (not just on the AWS accounts it scans).

See also: [ARCHITECTURE.md](ARCHITECTURE.md) and
[backend/README.md](../backend/README.md).
