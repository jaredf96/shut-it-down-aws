# Backend — Shut It Down

FastAPI + boto3 service that **read-only** scans an AWS account for resources
commonly left running after labs and tutorials.

> ⚠️ **Scanning never mutates AWS.** The one feature that can is guided
> cleanup: a deliberately tiny catalog (stop EC2, release an unassociated
> Elastic IP, delete an unattached EBS volume) that is **off by default** and
> clears seven independent gates before acting
> (`docs/SECURITY.md` § Cleanup actions are disabled by default). Terminating
> instances and deleting S3/RDS/NAT are deliberately unsupported — anything
> beyond the catalog you do manually in the AWS console after reviewing the
> dashboard.

> Requires **Python 3.10+** (the models use the `X | None` typing syntax).
> The Docker image and CI use Python 3.12.

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Make sure AWS credentials are configured (see below), then:
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive API (Swagger UI).

## Run in Docker

From the repo root:

```bash
docker compose up --build      # backend on http://localhost:8000
```

This mounts your `~/.aws` read-only into the container so it can scan your
account without baking credentials into the image.

## Tests & linting

```bash
pip install -r requirements-dev.txt   # adds pytest, moto, ruff

pytest                  # tests run fully offline via moto (no real AWS calls)
ruff check .            # lint
ruff format --check .   # formatting check (drop --check to auto-format)
```

The same checks run automatically in CI (`.github/workflows/ci.yml`).

## AWS credentials

boto3 picks up credentials automatically from any of:

- `~/.aws/credentials` (run `aws configure`)
- Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  optional `AWS_SESSION_TOKEN`, and `AWS_REGION`
- An attached IAM role (when later deployed to Lambda/ECS)

## Endpoints

| Method | Path                   | Description                                      |
| ------ | ---------------------- | ----------------------------------------------- |
| GET    | `/health`              | Liveness — process only, touches no dependency  |
| GET    | `/ready`               | Readiness — verifies DynamoDB; `503` if unreachable |
| GET    | `/me`                  | Current principal (workspace, user, role)       |
| GET    | `/users`               | List team members                               |
| POST   | `/users`               | Add a member, returns API key (admin only)      |
| DELETE | `/users/{id}`          | Remove a member, revokes key (admin only)       |
| GET    | `/accounts`            | List the workspace's registered AWS accounts    |
| POST   | `/accounts`            | Register an AWS account (admin only)            |
| DELETE | `/accounts/{id}`       | Remove an account registration (admin only)     |
| GET    | `/cleanup/actions`     | Supported cleanup actions + what's excluded     |
| GET    | `/cleanup/audit`       | Recent cleanup attempts (audit log)             |
| POST   | `/cleanup/execute`     | Run one cleanup action (admin, opt-in, audited) |
| POST   | `/notify`              | Send latest scan's alerts to channels (503 if off) |
| GET    | `/scan`                | Run every scanner; includes `alerts` (saves if on) |
| GET    | `/alerts`              | Alerts from the latest saved scan (503 if off)   |
| GET    | `/scans`               | List saved scans + `vs_previous` deltas (503 if off) |
| GET    | `/scans/diff`          | Compare two scans: `?from_id=…&to_id=…`          |
| GET    | `/scans/{scan_id}`     | Fetch one saved scan (503 if off, 404 if gone)  |

`GET /scan` accepts `?save=false` to skip persistence for that call.

Each resource carries **`created_at`** — the launch or creation time the AWS API
itself reports (EC2 `LaunchTime`, EBS/NAT `CreateTime`, RDS `InstanceCreateTime`,
ELB `CreatedTime`, S3 `CreationDate`). It is null for Elastic IPs, whose API
reports no allocation time at all. Age is what makes a scan a finding rather than
an inventory: "14 idle instances" versus "14 idle instances, the oldest running
87 days".

Every `GET /scan` response carries two arrays saying what the scan could **not**
see, each entry carrying the API error code and — in multi-account mode — the
account it belongs to:

- **`regions_failed`** — regions the sweep could not fully read (disabled,
  throttled, or not permitted).
- **`scanners_failed`** — whole scanners that could not run, as
  `{scanner, label, reason, account_id, account_label}`. S3 is global, so a
  failing `list_buckets` names no region to blame; a scanner can also fail
  before it reaches a region at all.

Either gap returns no resources, which is indistinguishable from having none, so
a scan that could not read three regions — or could not list buckets — has to say
so rather than present a partial inventory as a clean bill of health. Both are
empty when everything was read, and neither is stored with a saved scan.

### Workspace & auth

Every scan and alert is scoped to a `workspace_id`. Auth is **optional and off
by default**:

- **Local (default):** no API key needed. Requests run as an admin `local` user
  of the `default` workspace (override with `DEFAULT_WORKSPACE_ID`).
- **Shared deployment (`AUTH_REQUIRED=true`):** every data request must carry a
  valid API key, sent as either `Authorization: Bearer <key>` or
  `X-API-Key: <key>`.

There is no self-registration endpoint. Keys are minted by an admin — locally
that is you, via `POST /users` — and handed out:

```bash
curl -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"name": "TA", "role": "member"}'
# -> {"user_id": "…", "name": "TA", "api_key": "clc_…"}   (key shown once)

curl http://localhost:8000/scans -H 'X-API-Key: clc_…'
```

Data model (single table, prefixed partitions): `TENANT#<id>` holds that
workspace's scans, `APIKEY#<sha256(key)>` maps a key to its principal (only the
hash is stored), `USERS#<id>` the members. The `TENANT#` prefix is a frozen
legacy name kept deliberately — the logical model was renamed but stored data
was not, so there is no migration (see `app/repositories/dynamo.py` and
docs/DECISIONS.md D3). See `app/repositories/user_repository.py` and
`app/auth.py`.

### Teams & roles

A workspace has **users** with a role: **admin** (manage accounts + users) or
**member** (read-only management, full scan/alert access). Each user has their
own API key.

- `GET /me` returns the caller's principal (`{workspace_id, user_id, role, name}`).
- Admins add members with `POST /users` (returns the member's key, shown once)
  and remove them with `DELETE /users/{id}` (which revokes the key).
- **Scans are shared** across a workspace — every member sees the same history and
  alerts. For classrooms, register one AWS account per student; the dashboard's
  per-account filter gives the teacher a per-student view.

In local mode (no API key, `AUTH_REQUIRED` unset) the caller is an admin of the
default workspace, so everything is manageable without credentials.

### Guided cleanup (the only mutating feature)

The dashboard is read-only **except** for a deliberately narrow, opt-in cleanup
workflow. It is safe by construction — every layer must pass:

1. **Off by default.** `POST /cleanup/execute` returns
   `403 "Cleanup actions are disabled in this environment."` unless
   `ENABLE_CLEANUP_ACTIONS=true`.
2. **Admin only.** Members get `403`.
3. **Explicit confirmation.** `confirm_resource_id` must equal `resource_id`.
4. **Dry-run by default.** The request body defaults `dry_run: true` (preview);
   you must send `dry_run: false` to actually mutate.
5. **Live precondition re-check.** State is verified against AWS at execution
   time, never trusting the client (e.g. an EIP must still be unassociated).
6. **Everything is audited.** Every authenticated, well-formed attempt —
   refused, failed, dry-run, or executed — is recorded: to the audit log
   (`GET /cleanup/audit`) when persistence is on, and always to the
   application log. Real mutations are write-ahead audited
   (`docs/SECURITY.md` § Audit logging).

**Supported actions** (intentionally small):

| Action | Safety |
| ------ | ------ |
| `stop_ec2_instance` | reversible — Stop, never Terminate |
| `release_elastic_ip` | only when **unassociated** |
| `delete_unattached_ebs_volume` | destructive; only when **available** (unattached) |

**Not automated** (refused / warning-only): terminating EC2, deleting S3
buckets, deleting RDS databases, deleting NAT Gateways. These appear in
`GET /cleanup/actions` under `not_supported` so the UI stays transparent.

```bash
# Preview (dry run) — nothing changes:
curl -X POST localhost:8000/cleanup/execute -H 'Content-Type: application/json' -d '{
  "action": "stop_ec2_instance", "resource_id": "i-0abc", "confirm_resource_id": "i-0abc",
  "region": "us-east-1", "dry_run": true }'

# Execute for real (requires ENABLE_CLEANUP_ACTIONS=true + admin):
#   …same body with "dry_run": false
```

Durable audit needs persistence (DynamoDB); without it, attempts are still
recorded to the application logger.

### Minimum monthly cost (static + optional live pricing)

Every scanned resource is stamped with an `estimated_monthly_cost` (USD) and a
`cost_source`, and the scan `summary` carries a fleet total. Alerts are ranked by
spend within each severity.

**Read the number as a floor at on-demand list prices, not an estimate of the
bill.** Fixed hourly rates, EBS GB-month storage and RDS allocated storage are
priced. NAT Gateway data processing and S3 storage are not, so list-price spend
can only be higher than the figure — while Free Tier, credits, and Savings
Plans/Reserved discounts sit outside the model and can bring the actual bill
below it. The UI says "minimum monthly exposure" with the same scope. (The
field keeps the name `estimated_monthly_cost`: renaming it would churn
persisted scans, the alert model, and the provider contract without making it
any more accurate.)

- **`static`** (default) — a built-in price map (`app/pricing/static_prices.py`)
  for common lab resources. Credible ballpark, no AWS calls, always available.
- **`live`** — set `ENABLE_LIVE_PRICING=true` to refine estimates from the AWS
  Pricing API. Scoped on purpose: only NAT Gateway and EBS are wired to live
  lookups today; everything else still uses static. Add a method to
  `app/pricing/live_prices.py` and the service prefers it automatically — this
  is how the static estimator gets replaced gradually.
- **`unknown`** — usage-dependent resources we can't estimate (e.g. S3).

Live pricing is best-effort: any failure (missing permission, unknown region,
parse error) silently falls back to static, and results are cached in-process.

The two dimensions still missing are the expensive ones to fix. Data processing
and S3 storage need byte counts no Describe call returns — that means CloudWatch
reads and a wider IAM policy than a read-only scanner should carry. That is a
scope decision, not an oversight.

### Multi-account scanning

A workspace can register multiple AWS accounts (`POST /accounts` with a
cross-account `role_arn`). When any are registered, `GET /scan` assumes each
account's role via STS, scans it, and **tags every resource with its
`account_id` / `account_label`**. With none registered, the server's own
credentials are used (single-account / local — unchanged).

- Per-account failures (e.g. a role that can't be assumed) are collected in
  `account_errors` and never break the other accounts.
- Unreadable regions (`regions_failed`) and scanners that could not run
  (`scanners_failed`) are stamped with the account they occurred in —
  "us-west-1 failed" means little without saying whose.
- Resource identity for diffs/alerts includes `account_id`, so the same id in
  two accounts is never conflated.

**Cross-account setup:** in each target account, create a read-only IAM role
(the [least-privilege policy](#required-iam-permissions-read-only) above) whose
trust policy allows the scanner's principal to `sts:AssumeRole` — optionally
with an `external_id`. The scanner's own role needs `sts:AssumeRole` on those
role ARNs. See `app/aws/session.py` and `app/services/multi_account_service.py`.

### Alerts

Every `GET /scan` response includes an `alerts` array: notification-ready
signals derived from the scan, and (when a previous scan exists) from what
changed. Rules, in priority order, one alert per resource:

| Rule                    | Severity | Fires when                                       |
| ----------------------- | -------- | ------------------------------------------------ |
| `risk_increased`        | CRITICAL | a resource's risk level rose since the last scan |
| `new_billable_resource` | CRITICAL | a HIGH/MEDIUM resource appeared since last scan  |
| `new_review_resource`   | INFO     | a REVIEW resource (e.g. S3 bucket) appeared      |
| `high_risk_resource`    | WARNING  | a standing HIGH-risk resource                    |

Change-aware rules need history, so they only fire when a previous scan exists
(persistence on). With no history, only standing rules fire. `GET /alerts`
returns the same alerts computed from the latest saved scan vs the one before it.

### Notifications (email + Slack)

Alerts can be delivered to **Slack** (Incoming Webhook) and **email** (SMTP).
Channels are configured via env (see [`.env.example`](.env.example)); with none
set, delivery is a safe no-op.

- **Automatic:** set `NOTIFY_ON_SCAN=true` and every `GET /scan` pushes alerts to
  all configured channels (the response gains a `notifications` summary).
- **On demand:** `POST /notify` delivers the latest saved scan's alerts and
  returns a per-channel result.

Only alerts at or above `NOTIFY_MIN_SEVERITY` (default `WARNING`) are sent, so
INFO noise never pages anyone. A failing channel is reported as
`{"status": "error"}` and never breaks the others. Each notifier
(`app/notifiers/`) keeps message `format` separate from `send`, so message
construction is unit-tested without sending anything.

### History deltas (`vs_previous`)

`GET /scans` returns each scan with a `vs_previous` field summarizing how it
changed relative to the immediately older scan — powering the "+2 / −1 / ~3"
badges in the history sidebar. It is `null` for the earliest scan (no
predecessor), otherwise `{ "added", "removed", "changed", "unchanged" }`.

Deltas are computed on read in a single `Query` (the list fetches one extra scan
so even the oldest item in a page can be compared). See
`app/services/history_service.py`.

### Diffing two scans

`GET /scans/diff?from_id=<older>&to_id=<newer>` returns what changed between two
saved scans. Resources are matched across scans by
`(resource_type, region, resource_id)` and classified as:

- **added** — in the newer scan only
- **removed** — in the older scan only
- **changed** — in both, but `status` or `risk_level` differs (reported as
  `{field: {from, to}}`)
- **unchanged** — in both, identical (returned as a count)

Response shape:

```json
{
  "from": { "scan_id": "…", "created_at": "…", "summary": { … } },
  "to":   { "scan_id": "…", "created_at": "…", "summary": { … } },
  "added":   [ { … resource … } ],
  "removed": [ { … resource … } ],
  "changed": [ { "resource": { … }, "changes": { "status": { "from": "running", "to": "stopped" } } } ],
  "summary": { "added": 1, "removed": 1, "changed": 1, "unchanged": 4 }
}
```

## Scan history (DynamoDB persistence)

Persistence is **optional and off by default**. With no DynamoDB env vars set,
the app runs fully in-memory and the `/scans*` endpoints return `503`.

To enable it, set `DYNAMODB_TABLE_NAME` (see [`.env.example`](.env.example)).
Each `GET /scan` then saves a snapshot, and the history endpoints + the
dashboard sidebar light up.

**Data model** — one item per scan run in a single table:

| Attribute        | Notes                                                       |
| ---------------- | ----------------------------------------------------------- |
| `pk` (HASH)      | `"TENANT#<workspace_id>"` — frozen legacy prefix; scans are isolated per workspace |
| `sk` (RANGE)     | `scan_id` = `<ISO-8601 UTC>_<short uuid>` (time-sortable)    |
| `created_at`     | ISO timestamp                                               |
| `resource_count` | number of resources found                                   |
| `summary_json`   | small summary (counts by risk level)                        |
| `resources_json` | full resource list                                          |

Because `sk` is time-prefixed, listing a workspace's history is a single `Query`
with `ScanIndexForward=False` — no secondary index needed. Other record types
share the table under distinct prefixes (`APIKEY#`, `USERS#`, `ACCOUNTS#`,
`AUDIT#`).

**Create the table** (idempotent):

```bash
# Run from the backend/ directory. Real AWS:
DYNAMODB_TABLE_NAME=cloud-lab-scans python -m scripts.create_table

# Local DynamoDB (e.g. dynamodb-local on :8001):
DYNAMODB_TABLE_NAME=cloud-lab-scans \
DYNAMODB_ENDPOINT_URL=http://localhost:8001 \
python -m scripts.create_table

# …or simply, from the repo root:
make create-table
```

The easiest local setup is `docker compose up --build` from the repo root: it
starts a `dynamodb-local` container and the backend auto-creates the table
(`DYNAMODB_AUTO_CREATE=true`), so nothing touches your real AWS account.

## Required IAM permissions (read-only)

The simplest path is to attach the AWS-managed **`ReadOnlyAccess`** policy.
If you prefer a least-privilege custom policy, these actions are enough:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "ec2:DescribeNatGateways",
        "elasticloadbalancing:DescribeLoadBalancers",
        "rds:DescribeDBInstances",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLocation"
      ],
      "Resource": "*"
    }
  ]
}
```

If you enable DynamoDB persistence against **real AWS** (not local), also grant
the following on your table (skip this for `dynamodb-local`):

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:PutItem",
    "dynamodb:Query",
    "dynamodb:GetItem",
    "dynamodb:CreateTable",
    "dynamodb:DescribeTable"
  ],
  "Resource": "arn:aws:dynamodb:*:*:table/cloud-lab-scans"
}
```

(`CreateTable` is only needed if you use the create-table script or
`DYNAMODB_AUTO_CREATE`; drop it once the table is managed by Terraform/CDK.)

For **multi-account** scanning, the scanner's role additionally needs
`sts:AssumeRole` on each registered account's role ARN, and each target account
must grant the read-only policy above to a role that trusts the scanner.

If you enable **guided cleanup** (`ENABLE_CLEANUP_ACTIONS=true`), the role also
needs the matching write actions — only these three:
`ec2:StopInstances`, `ec2:ReleaseAddress`, `ec2:DeleteVolume`. Grant them only
in environments where cleanup is intended.

If you enable **live pricing** (`ENABLE_LIVE_PRICING=true`), the role needs
`pricing:GetProducts` (the Pricing API is global, queried via `us-east-1`).

## Project layout

```
app/
  main.py                       FastAPI routes
  config.py                     env-driven settings (persistence + auth toggles)
  auth.py                       API-key -> workspace dependency
  aws/session.py                default + assume-role boto3 sessions
  scanners/                     one read-only scanner per AWS service
  models/                       Resource, Alert, Account
  services/                     scan, diff, history, alerts, notification,
                                multi_account, cleanup (+ cleanup_actions)
  pricing/                      static_prices, live_prices, pricing_service
  notifiers/                    Slack + email delivery (base, slack, email)
  repositories/                 dynamo (shared), scan, user, account, audit
  lambda_handler.py             AWS Lambda entrypoint (Mangum)
  utils/                        region discovery helpers
scripts/create_table.py         idempotent table creation
../deploy/                      Terraform skeleton + deployment guide
```

Add a new service by dropping a `*_scanner.py` with a `scan()` function and
registering it in `scanners/__init__.py`.
