# CLAUDE.md — Cloud Lab Cleanup Dashboard

Project context for Claude Code. Read this before making changes.

## What this is

A read-only AWS scanner that finds resources left running after labs/tutorials
(EC2, EBS, Elastic IPs, NAT Gateways, ELB, RDS, S3), explains in plain English
why each costs money and roughly how much, and alerts on new risks. Built out to
a multi-tenant SaaS MVP: teams/roles, multi-account assume-role scanning, scan
history + diffing, Slack/email notifications, Stripe billing, and one carefully
guarded opt-in cleanup feature. Status: **tested proof-of-concept scaffold, not
production-hardened** (see `docs/SECURITY.md` → Production gaps).

Paths below assume the repo root is the project root (`backend/`, `frontend/`).

## Commands

Run from the repo root (Makefile drives everything):

```bash
make install-dev   # backend venv (.venv) + runtime + dev deps
make test          # 126 backend tests — pytest + moto, fully offline, no AWS creds needed
make lint          # ruff check + ruff format --check
make format        # auto-fix lint + reformat (run before committing)
make run           # backend on :8000 (uvicorn, reload)
make frontend-run  # frontend on :5173 (vite)
make build         # production frontend build (compile check)
docker compose up --build   # backend + local DynamoDB end-to-end
```

Single test: `cd backend && .venv/bin/pytest tests/test_alerts_service.py -k name -q`

**Python 3.10+ required** (models use `X | None`; pydantic evaluates it at
runtime). The system `python3` on macOS may be 3.9 — use `python3.12`.
`backend/.python-version` pins 3.12.3 for pyenv. CI and Docker use 3.12.

## Architecture (layers, strictly kept)

```
backend/app/
  main.py            routes only — thin; status codes + dependency wiring
  auth.py            API key → principal {tenant_id, user_id, role}; require_admin
  config.py          ALL feature toggles, env-driven, read lazily (functions, not constants)
  scanners/          one read-only scanner per AWS service + SCANNERS registry
  services/          orchestration: scan, multi_account, diff, history, alerts,
                     notification, cleanup (+cleanup_actions), billing
  pricing/           static_prices (baseline) + live_prices (Pricing API) + pricing_service
  notifiers/         Slack + email; `format` separated from `send` for testability
  repositories/      DynamoDB access: dynamo (shared), scan, tenant, user, account,
                     audit, billing
  models/            pydantic: Resource, Alert, Account/UserCreate, CleanupRequest
  aws/session.py     default_session + session_for_account (STS assume-role)
  lambda_handler.py  Mangum adapter
```

Rules that keep this maintainable:
- **Scanners are account-agnostic and read-only.** Uniform contract:
  `scan(regions: list[str] | None = None, session=None) -> list[Resource]`.
  Everything tenant-aware lives in services/repositories via an explicit,
  **optional** `tenant_id=` kwarg (default = local single-tenant mode).
- **Routes never contain business logic.** They resolve the principal, call a
  service, map errors to status codes.
- **Config is functions, not module constants** — so tests can monkeypatch env
  and pick up changes without re-imports.

## Data model — single DynamoDB table

One table, `pk` (HASH) + `sk` (RANGE), record families by pk prefix:
`TENANT#<t>` scans · `TENANTMETA#<t>` tenant+plan · `APIKEY#<sha256>` key→principal ·
`USERS#<t>` · `ACCOUNTS#<t>` · `AUDIT#<t>`. Tenant isolation is structural.
`scan_id = <ISO-8601-UTC>_<uuid8>` — time-sortable, so newest-first is a Query
with `ScanIndexForward=False`; **no GSIs**. Bulk payloads stored as JSON strings
(avoids Decimal issues); metadata native. Persistence is optional: no
`DYNAMODB_TABLE_NAME` → repositories are safe no-ops, history endpoints 503.

## Hard invariants — do not relax these

1. **Scanning never mutates AWS.** Only `Describe*`/`List*`/`Get*` calls in scanners.
2. **Cleanup safety gates** (`services/cleanup_service.py` + routes): env flag
   `ENABLE_CLEANUP_ACTIONS` off by default (403 with exact message "Cleanup
   actions are disabled in this environment."), admin-only, `confirm_resource_id`
   must equal `resource_id`, `dry_run` defaults to true, live precondition
   re-check against AWS (never trust the client), **every attempt audited**
   (including refusals/failures). Action catalog stays tiny: stop EC2, release
   unassociated EIP, delete unattached EBS. Terminate/S3/RDS/NAT deletion are
   deliberately NOT in the catalog — listed in `NOT_SUPPORTED` instead. No bulk ops.
3. **Everything off by default.** New features must degrade gracefully when
   their env vars are unset (no Stripe → manual plan mode; no DynamoDB →
   in-memory; no notifiers → no-op). Local dev must always run with zero config.
4. **Pricing/notifications must never break a scan.** Live pricing catches
   *all* exceptions and falls back to static; a failing notifier channel is
   reported per-channel, never raised.
5. **API keys stored only as SHA-256 hashes**; plaintext returned once at creation.
6. **Stripe webhooks are signature-verified**; manual plan endpoint returns 409
   when Stripe is configured (server-authoritative plans).

## Gotchas (learned the hard way — don't reintroduce)

- **Route ordering:** `/scans/diff` must be declared **before** `/scans/{scan_id}`
  in `main.py` or the path param swallows it.
- **IDs in URLs:** `scan_id` uses `_` as separator, never `#` (URL fragment —
  it silently truncated paths once).
- **Test fixture patching:** scanners import `get_regions` into their own
  namespace, and `services/scan_service.py` now resolves it once for the whole
  aggregate scan; `tests/conftest.py` patches it per-module (all 6 scanners
  **plus `scan_service`**) with signature `lambda session=None: [REGION]` — keep
  the `session` param and the `scan_service` entry, or scans silently return empty.
- **Region sweeps run concurrently** via `utils/concurrency.scan_regions`; each
  scanner splits its per-region body into a `_scan_region(region, session)`
  helper. boto3 client construction goes through `make_client` (lock-guarded —
  the botocore client factory isn't safe to call concurrently on a shared
  Session). Single-region calls (every test) stay on the calling thread, so moto
  never sees worker threads. Per-region errors are swallowed inside `scan_regions`.
- **moto quirks:** STS assume-role accepts any ARN (handy for multi-account
  tests); us-east-1 `get_bucket_location` returns `None`.
- **`.gitignore`:** root ignores `.env.*` but negates `!.env.example` — keep the
  negation or the example files vanish from git.
- **Alert/diff identity** is the 4-tuple `(resource_type, region, resource_id,
  account_id)` — account included so the same id in two accounts never conflates.
- The `dynamo_table` fixture in conftest is opt-in (not autouse); tests without
  it run with persistence disabled — that's intentional coverage of both modes.

## Conventions

- Ruff: line length 100, py312 target, rules E/F/I/UP/B (`backend/ruff.toml`).
  Always run `make format` then `make lint` before finishing.
- Tests colocate per feature (`tests/test_<feature>.py`), use moto via autouse
  fixtures in `conftest.py`, and must pass fully offline.
- Frontend: plain React + fetch client (`frontend/src/api/client.js`), one
  panel component per feature, styles in `frontend/src/styles.css` (BEM-ish).
- Keep READMEs in sync: endpoint tables in `backend/README.md`, feature list and
  env-var table in root `README.md`, plus `docs/ARCHITECTURE.md` / `SECURITY.md`
  when structure or security behavior changes.

## Extension recipes

- **New scanner:** add `app/scanners/<svc>_scanner.py` with the uniform `scan()`
  contract — put the per-region body in a `_scan_region(region, session)` helper
  and return `scan_regions(lambda r: _scan_region(r, session), regions, session)`
  (build clients via `make_client`). Register in `scanners/__init__.py` SCANNERS
  dict → per-service endpoint and aggregate scan come free. Add risk levels + plain-English
  `monthly_cost_risk`/`suggested_action`; populate `details` if cost-estimable;
  add a static price entry in `pricing/static_prices.py`; write moto tests.
- **New cleanup action:** add to `ACTIONS` in `services/cleanup_actions.py`
  with a live precondition check and dry-run message. Only reversible-leaning,
  single-resource actions; anything data-destructive beyond unattached EBS
  belongs in `NOT_SUPPORTED`. Note the matching IAM action in the READMEs.
- **New notifier:** subclass `Notifier` in `app/notifiers/`, keep
  `format`/`send` separate, wire into `notifiers_from_env()`.
- **New live-pricing dimension:** add a cached method on `LivePricer`, then a
  branch in `pricing_service._live_estimate` — static remains the fallback.

## Env vars (all optional; see backend/.env.example for the full annotated list)

`DYNAMODB_TABLE_NAME` / `DYNAMODB_ENDPOINT_URL` / `DYNAMODB_AUTO_CREATE` ·
`AUTH_REQUIRED` / `DEFAULT_TENANT_ID` / `ADMIN_TOKEN` ·
`SLACK_WEBHOOK_URL` / `SMTP_*` / `ALERT_EMAIL_*` / `NOTIFY_ON_SCAN` /
`NOTIFY_MIN_SEVERITY` · `ENABLE_LIVE_PRICING` · `ENABLE_CLEANUP_ACTIONS` (the
mutating master switch) · `STRIPE_SECRET_KEY` / `STRIPE_PRICE_ID` /
`STRIPE_WEBHOOK_SECRET` / `BILLING_*_URL`.

## Docs map

`docs/ARCHITECTURE.md` (components, data model, request flow) ·
`docs/SECURITY.md` (credentials, IAM, cleanup gates, production gaps) ·
`docs/DEMO.md` (10-minute walkthrough) ·
`backend/README.md` (API reference) · `deploy/README.md` (container/Lambda + Stripe).
