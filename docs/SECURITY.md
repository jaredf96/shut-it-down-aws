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
  account (`session_for_account`); each assumed session is named
  `shutitdown.<workspace>.<user>`, so the target account's own trail shows who
  caused the reads (scope and limits under Audit logging). The app's own
  principal never holds standing
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

That is the entire grant onboarding asks a scanned account for. Persistence,
assume-role and live pricing are permissions the *platform* holds in its own
account — nothing here asks a student to grant any of them, and the next section
is where they belong. The cleanup writes are not here either: which role would
need them depends on where the resource is, and cross-account cleanup is not
possible in this build at all — see § The platform's own runtime role.

The policy above is what `deploy/cloudformation/scanner-role.yaml` creates, and
`backend/tests/test_onboarding_template.py` parses both this document and that
template to assert they still say the same thing. An equal action list is only
least privilege if it is the whole grant, so the test also pins that the role
attaches no managed policy and that the template creates no other resource —
`AdministratorAccess` attached alongside would otherwise pass a comparison of
action lists.

### The platform's own runtime role

What the backend itself runs as. `deploy/cloudformation/platform-role.yaml`
creates it, `deploy/terraform/main.tf` emits the same document for an existing
role (as the `app_policy_json` output), and
`backend/tests/test_platform_role_template.py` pins the template against this
block:

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

Grant the rest **only when you opt into the corresponding feature**. No row below
is in the policy printed above:

| Feature | Extra permissions | Held by | Scope |
| --- | --- | --- | --- |
| Auto-create (dev) | `dynamodb:CreateTable` | the platform's runtime role | the app's table ARN, only with `DYNAMODB_AUTO_CREATE` |
| Live pricing | `pricing:GetProducts` | the platform's runtime role | `*` (the Pricing API is global) |
| **Guided cleanup** | `ec2:StopInstances`, `ec2:ReleaseAddress`, `ec2:DeleteVolume` | the platform's runtime role — single-account only, see below | only where cleanup is intended |

Those three cleanup writes are the **only** mutating actions the app can take,
and they map exactly to the three supported cleanup actions — nothing more.
`deploy/cloudformation/platform-role.yaml` and `deploy/terraform/main.tf` emit
exactly the three statements published above, and neither carries any action in
this table. That is what everything-off-by-default looks like at the IAM layer:
setting `ENABLE_CLEANUP_ACTIONS=true` grants nothing, and an operator has to
widen a policy on purpose.

**Where the cleanup writes have to live.** `cleanup_service._session` uses the
platform's own credentials for a request that names no `account_id`, and assumes
the registered scanner role for a request that names an account. So cleanup in
the platform's own account needs the three actions on the platform role — and
cleanup in a *registered* account would need them on the role the platform
assumes there, which is the read-only role `scanner-role.yaml` creates and
`backend/tests/test_onboarding_template.py` pins as read-only. **Cross-account
cleanup is therefore not possible in this build.** It refuses at IAM rather than
in the app, which is what `docs/DEMO.md` § 5 demonstrates; the separate
narrowly-scoped cleanup role it would need is listed under root `README.md`
§ Planned hardening. Do not widen a scanned account's role instead — that is the
grant this document exists to keep small.

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
   returns `403 "Cleanup actions are disabled in this environment."` The
   refusal is audited (`disabled`).
2. **Admin role** — members are rejected (`403`, audited as `forbidden`). This
   check runs *before* the env flag, so a non-admin's refusal never reveals
   whether cleanup is enabled.
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
`forbidden` / `disabled` / `confirmation_mismatch` / `unsupported_action` /
`unknown_account` / `precondition_failed` / `error` / `audit_unavailable`), a
detail message, and a timestamp. "Every attempt" means every authenticated,
well-formed request: the two refusals that used to happen before the service was
reached — a non-admin caller (`forbidden`) and the feature flag being off
(`disabled`) — are audited like any other outcome, because every gate lives in
the service (D13). What never reaches the trail is a request with no principal
to attribute: a missing or invalid API key (401) or a body that fails
validation (422) resolves no workspace to record under.

- Durable entries live in DynamoDB (`AUDIT#<workspace>`), workspace-scoped and
  time-sortable; `GET /cleanup/audit` lists them newest-first.
- The service **also** logs every attempt to the application logger, so there is
  a record even when persistence is disabled.
- **With persistence on, a real mutation is write-ahead audited.** Before any
  `dry_run: false` action touches AWS, the service persists an `initiated`
  entry; if that write fails, the action is refused with `audit_unavailable`
  (503) — persistence *enabled but not writable*, whether the store is
  unreachable or answers with an error, must not produce an unrecorded
  mutation. Persistence disabled (zero-config local mode) still runs, with
  log-only records as documented above. If the store fails *after* the
  mutation, the caller still receives the outcome and the `initiated` entry
  stands as outcome-unknown, logged at error level, instead of the attempt
  vanishing into a 500.

Because users are first-class (workspace + user id + role), every mutating
action in **this app's** audit trail is attributable to a specific user.

The scanned account's *own* CloudTrail is a second trail, and it is the one that
account's owner reads. Every `sts:AssumeRole` the app makes names its session
after the principal that caused it — `shutitdown.<workspace>.<user>` — so an
event there arrives as
`assumed-role/ShutItDownScannerRole/shutitdown.class-101.<user id>` rather than
as one constant shared by every user of every workspace.

Two limits, because this is an attribution aid and not an identity assertion.
The name is **asserted by the caller**: STS does not verify it, so it is
evidence about which principal this app believed was acting, not proof to the
account's owner. And with `AUTH_REQUIRED` unset there is exactly one principal
(`default`/`local`), so the name is the same for everyone using that install —
per-user attribution in the target account needs `AUTH_REQUIRED=true` and a key
per user. `SourceIdentity`, which STS does propagate and lock, is deliberately
not used: the target's trust policy would have to grant `sts:SetSourceIdentity`
or the AssumeRole fails outright, which would break every account already
onboarded with the published template (D18).

## Outbound email transport

The email notifier passes an explicit `ssl.create_default_context()` to both
`starttls()` and `SMTP_SSL`, so the relay's certificate chain is validated and
its hostname checked. Called bare — as it was — `smtplib.starttls()` builds
`ssl._create_stdlib_context()`: `CERT_NONE`, `check_hostname` False. Nothing
was verified, and `login()` then put the SMTP password on that connection.

What is guaranteed:

- **Verification is not optional.** There is no skip-verify variable, and
  adding one is a decided no (D15). The mode is coerced to a known value inside
  `EmailNotifier`, so the guarantee holds for any caller — not only for
  env-driven config.
- **`SMTP_CA_BUNDLE` is the supported path** for a private CA or a self-signed
  relay. It **replaces** the system trust store rather than adding to it, so
  trust becomes exactly that file. Do not set it when relaying through a public
  provider.
- **`SMTP_SECURITY=none` refuses to authenticate.** Plaintext remains available
  for a loopback or sidecar relay, but a username set alongside it is a refusal
  before the socket is opened, not a password on the wire.

The honest limit: a relay whose certificate does not match the name in
`SMTP_HOST` will no longer be reached. That is the point — but it means an
operator who was silently relying on an unverified connection sees email stop.
It stops loudly: a per-channel `error` in the `notifications` summary and a
`WARNING` in the application log, never a broken scan (invariant 4).

## Production gaps

Shut It Down is self-hosted and exposes no public multi-tenant API (D1), so the
gaps that mattered for a SaaS front door — open registration, per-customer abuse
protection — no longer apply. What remains is what an operator pointing this at
real AWS accounts should still know: credentials, blast radius, and the trail
you would want afterwards.

- **API keys, not sessions.** Auth is a single API key per user (hashed, but
  long-lived and not rotatable/expirable yet). Add key rotation/expiry, or move
  to OIDC/JWT sessions; consider per-key scopes. The browser client has no login
  at all: it reads `VITE_API_KEY` at build time, which Vite inlines into the
  bundle, so a build carrying a key must only ever be served to people entitled
  to that key.
- **No transport hardening in-app.** TLS, HSTS, security headers, and CORS lock-
  down are deployment concerns — the dev CORS config allows `localhost:5173`.
  Restrict origins and terminate TLS at the edge in production.
- **Audit log is append-only but not tamper-evident.** For compliance, ship
  audit events to an immutable store (e.g. CloudTrail Lake / S3 Object Lock).
- **Scan history has a hard per-scan ceiling.** A scan whose zlib-compressed
  resource list would push its DynamoDB item past ~290 KB is refused rather
  than split or truncated; the scan is still returned with `persisted: false`
  and the refusal is logged. On scan-shaped data that is roughly 6,800
  resources — pinned two-sidedly at 5,000 and 8,000 by
  `backend/tests/test_persistence.py::test_scan_ceiling_is_where_the_docs_say`
  — and a scan whose per-resource text is largely unique compresses about 3.5x
  instead of 14.7x and hits the ceiling nearer 3,500. An install at that scale
  needs the payload moved to S3 with the item holding a pointer.
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
