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

Two roles appear below and they are **not** the same grant. A **scanned account**
grants describe/list and nothing else. The **platform's own runtime role**
additionally persists scan history and assumes those scanner roles.

### A scanned account

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
| Multi-account | `sts:AssumeRole` | roles tagged `Project=shut-it-down-aws` (see below) |
| Live pricing | `pricing:GetProducts` | `*` (Pricing API is global) |
| **Guided cleanup** | `ec2:StopInstances`, `ec2:ReleaseAddress`, `ec2:DeleteVolume` | only where cleanup is intended |

The cleanup write permissions are the **only** mutating actions the app can
take, and they map exactly to the three supported cleanup actions — nothing more.
They belong to the **platform's own** runtime role: the Terraform skeleton emits
that policy document (`deploy/terraform/outputs.tf: app_policy_json`).

The policy above is the other one — what a **scanned** account grants. It is what
`deploy/cloudformation/scanner-role.yaml` creates, and
`backend/tests/test_onboarding_template.py` parses both this document and that
template to assert they still say the same thing. An equal action list is only
least privilege if it is the whole grant, so the test also pins that the role
attaches no managed policy and that the template creates no other resource —
`AdministratorAccess` attached alongside would otherwise pass a comparison of
action lists.

### The platform's own runtime role

What the backend itself runs as. `deploy/cloudformation/platform-role.yaml`
creates it, `deploy/terraform/main.tf` emits the same document for an existing
role, and `backend/tests/test_platform_role_template.py` pins the template
against this block:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AppTableAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem",
        "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:REGION:PLATFORM_ACCOUNT:table/TABLE_NAME"
    },
    {
      "Sid": "ReadOnlyScanning",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions", "ec2:DescribeInstances", "ec2:DescribeVolumes",
        "ec2:DescribeAddresses", "ec2:DescribeNatGateways",
        "elasticloadbalancing:DescribeLoadBalancers", "rds:DescribeDBInstances",
        "s3:ListAllMyBuckets", "s3:GetBucketLocation"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AssumeRegisteredScannerRoles",
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/*",
      "Condition": {
        "StringEquals": { "aws:ResourceTag/Project": "shut-it-down-aws" }
      }
    }
  ]
}
```

`DescribeTable` is not decoration: `GET /ready` calls it on every probe, so a
role without it reports the backend unready while history reads and writes work.

**Why `sts:AssumeRole` is scoped by a tag rather than by ARN.** The registered
ARNs are not knowable when this policy is written — onboarding is self-service,
and the scanner role's name is overridable. Scoping to `role/*` with no condition
would let the platform assume anything that happens to trust it; a hard-coded
list would need a platform redeploy per student. The tag is the one property
every role `scanner-role.yaml` creates carries. It is a **namespace guard, not an
authorization boundary** — the account's owner controls its tags exactly as it
controls its trust policy. The boundary remains where it always was: the target's
trust policy plus its external ID.

## Onboarding an account

An instructor onboards each lab account by having its owner run one
CloudFormation stack. Nobody hands over keys, and the platform never holds
standing access.

Placeholders in the command blocks below are bare `UPPERCASE` words, not
`<ANGLE_BRACKETED>` ones, so that a block survives being copied whole: `<` is a
shell redirect, and a bracketed placeholder fails with a syntax error before the
command reaches AWS. Substitute them.

**Step 0 — the platform's own role has to exist first, and the backend has to
run as it.** `PlatformRoleArn` in step 2 is the role the backend runs as, and
every target's trust policy names it. Create it once per install:

```bash
aws cloudformation deploy \
  --template-file deploy/cloudformation/platform-role.yaml \
  --stack-name shut-it-down-platform-role \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides OperatorPrincipalArn=arn:aws:iam::PLATFORM_ACCOUNT:role/YOUR_OPERATOR_ROLE
```

Creating it is not enough — the backend has to actually assume it, or targets
will refuse the backend's own credentials. They trust the platform role, not you:

```ini
# ~/.aws/config
[profile shut-it-down]
role_arn = arn:aws:iam::PLATFORM_ACCOUNT:role/shut-it-down-backend
source_profile = your-normal-profile
region = us-east-1
```

```bash
AWS_PROFILE=shut-it-down make run
```

Hosted deployments skip this stack entirely: an ECS task or a Lambda already runs
as a role, and `deploy/README.md` says to attach the same policy to it. Note the
lifecycle warning at the top of `platform-role.yaml` — deleting and recreating
this role strands every target that already trusts it.

**The rest of the order is forced by the external ID.** The stack takes it as a
parameter, so it has to exist before the role does — and the role ARN the
platform registers does not exist until the stack has run:

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
      PlatformRoleArn=arn:aws:iam::PLATFORM_ACCOUNT:role/shut-it-down-backend \
      ExternalId=THE_GENERATED_ID
```

3. Register the stack's `RoleArn` output in the dashboard (**Accounts → Add
   account**) with **the same external ID**. Scans fan out to it from then on.

**Step 3 needs persistence, and the normal mode does not have it.** Registered
accounts live in DynamoDB: `/accounts` returns 503 when `DYNAMODB_TABLE_NAME` is
unset, and the dashboard hides the accounts panel entirely rather than offering a
form that cannot save. Zero-config is otherwise the *normal* way to run this
(D4), so this is the one place onboarding needs more than the defaults — set
`DYNAMODB_TABLE_NAME` before you start. Skip it and you get a role in the target
account with nowhere to register it, while scans go on quietly using the
platform's own credentials.

**`PlatformRoleArn` is the backend's own role, not the account root.** The
template rejects a root ARN outright. An account-root principal delegates the
trust to every principal in that account, which is a much wider grant than "the
one role my scanner runs as" — and the external ID does not narrow it back down.

**What the external ID is for.** It is confused-deputy protection: it stops
someone from persuading the platform to assume a role on their behalf. It is
**not** a secret that makes a role ARN safe to publish, and knowing a role ARN
never granted anyone the right to assume it.

**Where it is readable.** It has to be stored in plaintext — assuming the role
needs the literal value — but `GET /accounts` does not return it. Registration
echoes it once and it is never listed again, which is how API keys are handled
and for the same reason: that route is open to every workspace member, while
registering and deleting accounts are admin-only. Listings carry
`has_external_id` instead. An operator who loses the value re-runs the target's
stack with a fresh one; nothing can read it back out of the API.

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
  Consider soft-delete/snapshot-first, per-workspace allow-lists, and a second
  approver for destructive actions.
- **Outbound notifications are unthrottled.** There is no deduplication,
  cooldown, or send-rate limit, so a persistent finding re-alerts on every scan
  and a noisy account can flood a channel. Delivery is also synchronous: a slow
  or hanging SMTP server adds its timeout (up to ~10s) to the request.
- **`POST /notify` is not admin-gated.** It resolves the caller with
  `get_current_workspace`, so any authenticated member of a workspace can trigger
  outbound messages to that workspace's configured Slack/email channels. Whether
  sending should be admin-only is a product decision, deliberately left open —
  but it is an abuse vector worth closing before untrusted members exist.
- **Data lifecycle.** No retention/TTL on scans or audit entries; add DynamoDB
  TTL and a workspace data-deletion path.
- **Observability.** Add structured logging, metrics, tracing, and alerting on
  the service itself (not just on the AWS accounts it scans).

See also: [ARCHITECTURE.md](ARCHITECTURE.md) and
[backend/README.md](../backend/README.md).
