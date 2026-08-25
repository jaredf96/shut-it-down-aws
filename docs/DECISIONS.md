# Decisions

Why this file exists: the architecture here is sound, but several **seams** were
built to keep options open — `AUTH_REQUIRED` optional, `tenant_id=None` falling
back to local, billing behind `billing_enabled()`. An open seam with no recorded
choice does not read as a decision. It reads as an open question, and it gets
re-encountered and re-litigated every session, at a small cost each time.

This file records which side of each seam is live. Add an entry when a decision
gets made, not when the code changes — the point is to stop paying the tax before
the refactor happens.

---

## D1 — Shut It Down is a self-hosted portfolio project, not a commercial SaaS

**Decided:** 2026-08-25 · **Status:** decided, code not yet aligned

A production-conscious AWS lab-management portfolio project: a real
local/self-hosted scanner for individuals and instructors, supported by a safe
public simulation. **Not** a commercial SaaS.

The end state, so it stays visualizable:

> An individual or instructor runs Shut It Down against their own AWS account, or
> assumes read-only roles into N student lab accounts. No credentials needed to
> start; optional API keys if TAs need access. It finds resources left running
> after labs, explains in plain English what they cost, alerts on new risk, keeps
> scan history and an audit trail, and can clean up on request. A public demo
> build fed by `demo-data/` fixtures lets anyone see it working with no AWS
> account and no API client in the bundle.

Every capability in that paragraph already exists. Reaching the end state is
subtraction, not construction.

**Why:** the repo was building two products at once. The demo/scanner was live and
the SaaS was labelled "shelved" in `CLAUDE.md` while remaining wired into
`main.py` — tenant creation, plan limits, Stripe checkout, all in the request
path. Every design question silently forked into "for which product?"

---

## D2 — The billing/subscription layer is removed, not shelved

**Decided:** 2026-08-25 · **Status:** executed

Follows from D1. "Shelved" was not true — the code was live. Either state it is
built, or remove it. Removing it.

Removed:
- `backend/app/services/billing_service.py` (119 lines)
- `backend/app/repositories/billing_repository.py` (58 lines)
- `backend/app/repositories/tenant_repository.py` (49 lines) — collapses to a constant
- Stripe checkout, customer-portal, and plan-limit routes in `main.py`
- The plan-limit gates `user_limit_reached` / `account_limit_reached`

~230 lines plus a handful of endpoints. Not a rewrite.

**Not lost:** extracted first to `~/Documents/Claude/fastapi-stripe-saas-reference`
as a standalone reusable reference implementation — see that repo's `SPEC.md`.
The extraction target is deliberately *more* than what exists here (webhook
signature verification, idempotency, a real subscription state machine), because a
thin copy of these files is not worth keeping. Git history holds the originals
regardless.

**Sequence:** extract to the reference repo → verify it stands alone → remove here.
Not the other way round.

---

## D3 — Multi-account yes, multi-tenant no

**Decided:** 2026-08-25 · **Status:** executed

`tenant_id` currently does two unrelated jobs:

1. **SaaS isolation** — keeping paying customer A's data away from customer B.
   Dies with D1.
2. **A partition key** — `ACCOUNTS#<tenant_id>`, `TENANT#<tenant_id>` in DynamoDB.
   Self-hosted, this is a constant from `config.default_tenant_id()`.

Job 2 is most of the 125 call sites and is already benign. Rename to
`workspace_id` (or pin it) so the name stops implying job 1.

**An instructor managing a class is a multi-account problem, not a multi-tenant
one.** `multi_account_service` — assume read-only roles into N student lab
accounts, tag every resource with its account, never let one account's failure
break the others — is the core instructor feature. It stays.

Kept for the same reason: `account_repository`, `auth.py`, `user_repository`,
`cleanup_service`, `audit_repository`, `scan_repository`.

### How the rename is done

**Rename the logical model end-to-end; freeze the storage schema.**

Logical vocabulary becomes `workspace` everywhere a human or a caller sees it:
Python identifiers, API payloads, frontend contracts and providers, tests, docs.

Storage is **frozen legacy** and deliberately not renamed: partition prefixes
`TENANT#`, `ACCOUNTS#`, `USERS#`, `AUDIT#` and every persisted `tenant_id`
attribute stay exactly as they are. **No data migration.** Self-hosted means the
data lives on each operator's own infrastructure; a migration would have to be
idempotent, partial-failure-safe, and tested on every install, for a naming
change nobody can see.

**This mismatch is deliberate, and this paragraph is why it exists.** Finding
`TENANT#` in the repository layer is not a bug or an oversight — it is a frozen
storage name behind a translation boundary.

Translation is **explicit and record-specific**, not generic. The only record
that persists a `tenant_id` *attribute* crossing a public boundary is the API-key
principal, so the mapping lives in `user_repository` as
`_principal_to_storage()` / `_principal_from_storage()`. `dynamo.py` stays
infrastructure plumbing and never silently rewrites arbitrary dicts — a generic
mapper there would hide the fact that exactly one record type needs this.

Every other repository already builds its public response from an explicit
allowlist (`_PUBLIC_FIELDS`, `_strip_keys`, or a literal dict), and `_get_raw()`
is private with internal callers only. Those are already correct; leave them
alone. Remove raw-return patterns only where they genuinely cross a repository's
public boundary.

**Env var:** `DEFAULT_WORKSPACE_ID` is canonical. `DEFAULT_TENANT_ID` remains a
deprecated fallback; the canonical name wins when both are set, and the fallback
logs a deprecation warning **once per process** (config resolvers are functions,
not constants — an unguarded warning fires on every read).

**Accepted API break.** The response shape changes for the frontend, which is a
real consumer — this is a coordinated break landed in the same change, not a
break with no consumers. There is no supported external compatibility
commitment, so no versioning or deprecation window applies. Both providers and
`contract.d.ts` move together; `providerContract.test.js` enforces it.

Tests that pin the boundary:
- `/me` and user creation return `workspace_id` and never `tenant_id`
- reading a legacy API-key row that stores `tenant_id` resolves correctly
- new writes still produce the frozen storage representation
- env-var precedence, and the legacy warning fires once

---

## D4 — Auth stays optional and local-first

**Confirmed:** 2026-08-25 · **Status:** already true in code, no change needed

`AUTH_REQUIRED` unset is the **primary** mode, not a dev convenience: no API key,
default workspace, admin `local` user. API keys are the opt-in path for shared
deployments (a TA, a shared box).

Recorded because D1 changes what this seam *means*. It used to read as "SaaS mode
off"; it now reads as "the product's normal operating mode."

`docs/SECURITY.md` → "Production gaps" needs revisiting under D1: entries about
open tenant registration and public-API abuse protection stop applying once there
is no public multi-tenant API. The ones about credential handling, least-privilege
IAM, and TLS still apply and matter more.

---

## D5 — The demo build boundary holds

**Confirmed:** 2026-08-25 · **Status:** already true in code, no change needed

Two deployment surfaces, one codebase. The frontend picks between fixture data and
the real API at build time via the provider in `frontend/src/data/`; components
never import `api/client.js` directly. `make demo-bundle-check` asserts no API
client leaked into the demo bundle.

D1 makes this **more** load-bearing, not less — the public simulation is now half
the stated product rather than a marketing page.

---

## Template

```markdown
## D<n> — <the decision, as a sentence>

**Decided:** YYYY-MM-DD · **Status:** decided | executed | superseded by D<n>

<What was chosen.>

**Why:** <what made this ambiguous, and what tipped it>

**Consequences:** <what changes in code, docs, or scope>
```
