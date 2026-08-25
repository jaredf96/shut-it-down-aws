# CLAUDE.md — Shut It Down

Project context for Claude Code. Read this before making changes.

## What this is

A read-only AWS scanner that finds resources left running after labs/tutorials,
explains in plain English why each costs money and roughly how much, and alerts
on new risks. Full feature list in the root `README.md`. Status: **tested
proof-of-concept scaffold, not production-hardened** (`docs/SECURITY.md` →
Production gaps).

**Two deployment surfaces, one codebase.** The public demo is a static build fed
by `demo-data/` fixtures — no credentials, no API client in the bundle. The
authenticated app talks to the real API. The frontend picks between them at
build time via the provider in `frontend/src/data/`; components never import
`api/client.js` directly. Keep that boundary. The SaaS build-out (Cognito,
queued workers, Stripe lifecycle) is deliberately **shelved**, not in progress.

Paths below assume the repo root is the project root (`backend/`, `frontend/`).

## Commands

`make help` lists every target. The ones you actually run:

```bash
make install-dev        # backend venv (.venv) + runtime + dev deps
make test               # pytest + moto, fully offline, no AWS creds needed
make format && make lint
make demo-fixtures      # regenerate demo-data/ from the real scanners
make demo-bundle-check  # build the demo + assert no API client leaked in
npm --prefix frontend test -- --run && npm --prefix frontend run typecheck
```

Single test: `cd backend && .venv/bin/pytest tests/test_alerts_service.py -k name -q`

**Python 3.10+ required** (models use `X | None`; pydantic evaluates it at
runtime). The system `python3` on macOS may be 3.9 — use `python3.12`.
`backend/.python-version` pins 3.12.3 for pyenv. CI and Docker use 3.12.

## Architecture (layers, strictly kept)

`backend/app/` layers top-down: `main.py` (routes only) → `services/`
(orchestration) → `scanners/` · `pricing/` · `notifiers/` · `repositories/`, over
`models/` (pydantic) and `aws/session.py`. `docs/ARCHITECTURE.md` has the
component map, scanner contract, and request flow.

Rules that keep this maintainable:
- **Scanners are account-agnostic and read-only.** Uniform contract:
  `scan(regions=None, session=None, failed_regions=None) -> list[Resource]`.
  `failed_regions` is an optional `dict[str, str]` the sweep fills with
  `region -> reason` for regions it could not read; the return type stays a
  plain list so nothing downstream has to unpack a tuple. A scanner that cannot
  run **at all** raises — `scan_all` records it under `scanners_failed` and
  keeps going. Never return `[]` for a failure: that is "couldn't see" rendered
  as "nothing there". Everything workspace-aware lives in services/repositories
  via an explicit, **optional** `workspace_id=` kwarg (default = the local
  workspace).
- **Routes never contain business logic.** They resolve the principal, call a
  service, map errors to status codes.
- **Config is functions, not module constants** — so tests can monkeypatch env
  and pick up changes without re-imports.

## Data model — single DynamoDB table

One table, `pk` (HASH) + `sk` (RANGE), record families by pk prefix:
`TENANT#<w>` scans · `APIKEY#<sha256>` key→principal · `USERS#<w>` ·
`ACCOUNTS#<w>` · `AUDIT#<w>`. Workspace isolation is structural. **Storage names
are frozen legacy:** the logical model is `workspace`, the stored prefixes still
say `TENANT#`, and the API-key record still stores a `tenant_id` attribute —
deliberately, so no install needs a migration (D3). The one translation lives in
`user_repository._principal_to_storage` / `_principal_from_storage`; do not add
a generic mapper to `dynamo.py`.
`scan_id = <ISO-8601-UTC>_<uuid8>` — time-sortable, so newest-first is a Query
with `ScanIndexForward=False`; **no GSIs**. Bulk payloads stored as JSON strings
(avoids Decimal issues); metadata native. Persistence is optional: no
`DYNAMODB_TABLE_NAME` → repositories are safe no-ops, history endpoints 503.

## Hard invariants — do not relax these

1. **Scanning never mutates AWS.** Only `Describe*`/`List*`/`Get*` calls in scanners.
2. **Cleanup safety gates** (`services/cleanup_service.py` + routes): env flag
   `ENABLE_CLEANUP_ACTIONS` off by default (403 with exact message "Cleanup
   actions are disabled in this environment."), admin-only, `confirm_resource_id`
   must equal `resource_id`, `dry_run` defaults to true, a named `account_id`
   must be one the workspace registered (never fall back to default credentials —
   that runs the action against the host account), live precondition re-check
   against AWS (never trust the client), **every attempt audited**
   (including refusals/failures). Action catalog stays tiny: stop EC2, release
   unassociated EIP, delete unattached EBS. Terminate/S3/RDS/NAT deletion are
   deliberately NOT in the catalog — listed in `NOT_SUPPORTED` instead. No bulk ops.
   The dashboard sends the account of the finding it is acting on: the service is
   handed an id and a region and cannot infer the account, so the gate above
   cannot close the case on its own.
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
  namespace, and `scan_service.py` resolves it once for the whole aggregate
  scan; `tests/conftest.py` patches it per-module (all 6 scanners **plus
  `scan_service`**) with signature `lambda session=None: [REGION]` — keep the
  `session` param and the `scan_service` entry, or scans silently return empty.
- **Region sweeps run concurrently** via `utils/concurrency.scan_regions`. Build
  clients through `make_client` — it lock-guards botocore's client factory, which
  isn't safe to call concurrently on a shared Session. Single-region calls (every
  test) stay on the calling thread, so moto never sees worker threads.
- **moto quirks:** STS assume-role accepts any ARN (handy for multi-account
  tests); us-east-1 `get_bucket_location` returns `None`.
- **`.gitignore`:** root ignores `.env.*` but negates `!.env.example` — keep the
  negation or the example files vanish from git.
- **Alert/diff identity** is the 4-tuple `(resource_type, region, resource_id,
  account_id)` — account included so the same id in two accounts never conflates.
- The `dynamo_table` fixture in conftest is opt-in (not autouse); tests without
  it run with persistence disabled — that's intentional coverage of both modes.
- **Local DynamoDB gets dummy credentials.** botocore signs every request through
  the ambient credential chain, so an expired SSO session used to break *local*
  persistence too. `repositories/dynamo.py` supplies placeholder creds for a
  narrow host allowlist (`localhost`, `127.0.0.1`, `::1`, `dynamodb-local`).
  Never widen it — dummy creds must not reach a real endpoint.
- **Unhandled exceptions bypass CORS.** Starlette's outermost error handler runs
  outside `CORSMiddleware`, so a raw 500 arrives with no
  `Access-Control-Allow-Origin` and the browser reports a *CORS* error, hiding the
  real failure. `ErrorEnvelopeMiddleware` is registered **before** CORS so CORS
  stays outermost (later `add_middleware` wraps earlier) — keep that order.
- Repository connectivity/credential failures raise `PersistenceUnavailable`
  (→ structured 503). `ClientError` is *not* translated: it means DynamoDB
  answered, and callers like `ensure_table` depend on reading its code.
- **The provider boundary is a contract.** Demo and live providers obtain data
  differently but return identical shapes, enforced by `src/data/contract.d.ts`
  (compile time), the provider-contract test (runtime), and
  `test_demo_fixtures.py` (against the real Pydantic models). Changing a
  service's return shape means updating the contract *and* regenerating
  fixtures — the demo computes its own diff locally and silently diverged once
  already: `changed` entries are `{resource, changes}` keyed by field, **not** a
  flat resource with an array.
- **`runScan()` returns a provider-normalized `as_of`, never the endpoint's
  own timestamp.** `GET /scan` sends none — it is modelled honestly as
  `LiveScanResponse` (nullable `scan_id`, no `created_at`, since a live scan is
  not a saved one) — so each provider supplies the field the contract requires:
  the API provider stamps the moment the response lands, the demo returns its
  fixture's `created_at`. That is what keeps resource ages measured against
  *when the scan ran*. Letting it fall back to render time would creep the
  demo's fixture ages upward every day and outrun the committed screenshots in
  `docs/img/` — the same drift the `asOf` prop on `ResourceTable` exists to
  prevent. Saved scans are unaffected: they carry their own required
  `created_at`.
- **Demo fixtures are generated, never hand-edited.** `make demo-fixtures` runs
  the real scanners over a seeded moto sandbox. The seed matters: without it,
  every regeneration churns all IDs and invalidates the committed screenshots.
- **A new scan-table column can silently clip the last one.** `.page`'s
  max-width is sized to fit the table beside the history sidebar; re-measure
  `.table-wrapper` scrollWidth vs clientWidth (the CSS comment has the numbers).

## Conventions

- Ruff: line length 100, py312 target, rules E/F/I/UP/B (`backend/ruff.toml`).
  Always run `make format` then `make lint` before finishing.
- Tests colocate per feature (`tests/test_<feature>.py`), use moto via autouse
  fixtures in `conftest.py`, and must pass fully offline.
- Frontend: plain React, one panel component per feature, styles in
  `frontend/src/styles.css` (BEM-ish). **Components never import
  `api/client.js`** — they go through the provider (`frontend/src/data/`).
  Frontend tests (vitest + RTL) and `typecheck` (tsc, scoped to `src/data`)
  both run in CI.
- Keep docs in sync: endpoint tables in `backend/README.md`, feature list and
  env-var table in root `README.md`, plus `docs/ARCHITECTURE.md` /
  `docs/SECURITY.md` when structure or security behavior changes.

## Extension recipes

- **New scanner:** follow the contract in `docs/ARCHITECTURE.md` § Scanner
  contract. Register in `scanners/__init__.py` — `SCANNERS` **and**
  `SCANNER_LABELS` (the display name shown when it is unavailable). Add risk
  levels + plain-English `monthly_cost_risk`/`suggested_action`, `created_at`
  from whatever launch/creation time the API returns, `details` if
  cost-estimable, a `pricing/static_prices.py` entry, and moto tests.
  There is deliberately **no** per-service endpoint: one used to come free with
  registration and answered with the server's own inventory while `/scan`
  answered with the workspace's.
- **New cleanup action:** add to `ACTIONS` in `services/cleanup_actions.py`
  with a live precondition check and dry-run message. Only reversible-leaning,
  single-resource actions; anything data-destructive beyond unattached EBS
  belongs in `NOT_SUPPORTED`. Note the matching IAM action in the READMEs.
- **New notifier:** subclass `Notifier` in `app/notifiers/`, keep
  `format`/`send` separate, wire into `notifiers_from_env()`.
- **New live-pricing dimension:** add a cached method on `LivePricer`, then a
  branch in `pricing_service._live_estimate` — static remains the fallback.

## Docs map

**`docs/DECISIONS.md` — read first.** Records which side of each open seam is live
(product scope, billing, tenancy). Several seams here were deliberately built to
keep options open; that file says which option was taken, so they stop reading as
open questions.

`docs/ARCHITECTURE.md` (components, data model, request flow) ·
`docs/SECURITY.md` (credentials, IAM, cleanup gates, production gaps) ·
`docs/DEMO.md` (cross-account sandbox recording script) ·
`backend/README.md` (API reference) · `deploy/README.md` (container/Lambda + Stripe).
All env vars are annotated in `backend/.env.example`.

Read `deploy/terraform/demo/README.md` before touching `deploy/` — it carries the
demo stack's rationale and the operational hazards that have caught people out
(pricing-plan restrictions, the bucket policy as kill switch, edge caches
surviving a grant removal, failed applies writing state).
