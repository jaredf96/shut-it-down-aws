# Decisions

Why this file exists: the architecture here is sound, but several **seams** were
built to keep options open — `AUTH_REQUIRED` optional (still is, and that is the
normal mode — D4), `tenant_id=None` falling back to local (now `workspace_id` —
D3), billing behind `billing_enabled()` (removed outright — D2). An open seam
with no recorded choice does not read as a decision. It reads as an open
question, and it gets re-encountered and re-litigated every session, at a small
cost each time.

This file records which side of each seam is live. Add an entry when a decision
gets made, not when the code changes — the point is to stop paying the tax before
the refactor happens.

A **Status** only moves to `executed` once the full verification suite passes —
`make test`, `make lint`, the frontend tests and typecheck, and
`make demo-bundle-check` — so no commit claims a decision is done while the repo
still contradicts it.

---

## D1 — Shut It Down is a self-hosted portfolio project, not a commercial SaaS

**Decided:** 2026-08-25 · **Status:** executed

Carried out by D2 (billing removed), D3 (tenant -> workspace), and D4/D5 (docs
aligned). The code and the docs now state this product and no other.

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

**Consequences:** `CLAUDE.md` § What this is for and `README.md` § Status state
this product and no other. Everything else is delegated — D2 removes the billing
code, D3 renames the model, D4 and D5 align the docs. **That delegation is why
this entry's `executed` cannot be verified on its own:** it is only as true as
the four entries it names, and it was in fact false for a week, because D4
aligned `docs/SECURITY.md` and not `README.md` (D9).

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
- `ADMIN_TOKEN` (`config.admin_token()` + env) — it gated exactly one endpoint,
  `POST /tenants`, which went with `tenant_repository`

~230 lines plus a handful of endpoints. Not a rewrite.

**Not lost:** extracted first to `~/Documents/Claude/fastapi-stripe-saas-reference`
as a standalone reusable reference implementation — see that repo's `SPEC.md`.
The extraction target is deliberately *more* than what exists here (webhook
signature verification, idempotency, a real subscription state machine), because a
thin copy of these files is not worth keeping. Git history holds the originals
regardless.

**Sequence:** extract to the reference repo → verify it stands alone → remove here.
Not the other way round.

**Consequences:** the files and routes listed above are gone from `backend/app/`,
and `git grep ADMIN_TOKEN` now returns only this entry's own record of it.
`CLAUDE.md` states billing is gone rather than shelved; `docs/ARCHITECTURE.md`'s
record table marks `TENANTMETA#` retired, because D2 deleted its owner. The
extraction target lives outside this repo, at
`~/Documents/Claude/fastapi-stripe-saas-reference`.

---

## D3 — Multi-account yes, multi-tenant no

**Decided:** 2026-08-25 · **Status:** executed

At the time of the decision, `tenant_id` did two unrelated jobs:

1. **SaaS isolation** — keeping paying customer A's data away from customer B.
   Died with D1.
2. **A partition key** — `ACCOUNTS#<tenant_id>`, `TENANT#<tenant_id>` in DynamoDB.
   Self-hosted, that is a constant, now resolved by `config.default_workspace_id()`.

Job 2 was most of the 125 call sites and was already benign. It was renamed to
`workspace_id` so the name stops implying job 1.

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

Storage is **frozen legacy** and deliberately not renamed. Every partition
prefix and every persisted `tenant_id` attribute stays exactly as it is:

| Prefix | Holds | Status |
| --- | --- | --- |
| `TENANT#<workspace>` | saved scans | live |
| `ACCOUNTS#<workspace>` | registered AWS accounts | live |
| `USERS#<workspace>` | team members | live |
| `AUDIT#<workspace>` | cleanup attempts | live |
| `APIKEY#<sha256(key)>` | principal (stores the workspace as `tenant_id`) | live |
| `TENANTMETA#<workspace>` | the old tenant record | **RETIRED** |

**No data migration.** Self-hosted means the data lives on each operator's own
infrastructure; a migration would have to be idempotent, partial-failure-safe,
and tested on every install, for a naming change nobody can see.

**This mismatch is deliberate, and this paragraph is why it exists.** Finding
`TENANT#` in the repository layer is not a bug or an oversight — it is a frozen
storage name behind a translation boundary.

**`TENANTMETA#` is retired, not missing.** It held the tenant record —
`{name, created_at}`, later plan and subscription status — at sk `#`, and its
only owner was `tenant_repository.py`, which D2 deleted. Nothing reads, writes,
or deletes those rows now, and no code refers to the prefix at all. An install
that ran an earlier version still has them: they are **orphaned on purpose** and
left in place, for the same reason nothing else was migrated. Do not add a
cleanup pass, and do not read the rows as garbage that escaped one — this line
is the record that they were left deliberately.

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

### Where "tenant" is still allowed

Standing policy, not a one-time cleanup check. The routine check is
`git grep -in tenant` over `backend/app`, `backend/tests` and `frontend/src`,
but the policy holds wherever the word appears. Permitted **only** in:

- **Frozen storage names** — the `TENANT#` and `TENANTMETA#` prefixes and the
  stored `tenant_id` attribute — and the functions that translate them
  (`_STORED_WORKSPACE_ATTR`, `_principal_to_storage`, `_principal_from_storage`).
- **Documentation and comments explaining the frozen-storage mismatch**, in
  code or in prose. A frozen name with no explanation reads as an oversight and
  gets "fixed", so the explanations are load-bearing and have to be free to name
  the legacy thing. This covers the module docstrings in `dynamo.py`,
  `scan_repository.py`, `account_repository.py` and `user_repository.py`;
  explanatory comments in tests, including annotations on stubbed API responses
  that say why the wire shape is `workspace_id`; and the data-model sections of
  `CLAUDE.md` and `docs/ARCHITECTURE.md`.
- **The deprecated `DEFAULT_TENANT_ID` fallback** and its warning.
- **Compatibility tests** that assert the legacy shape on purpose.
- **Historical or explanatory text** in this file.

Everything else is active logical vocabulary and says `workspace`. A new hit
outside that list is a rename that was missed, not a new convention.

**Consequences:** `workspace_id` in Python, on the wire, and in
`frontend/src/data/contract.d.ts`. `DEFAULT_WORKSPACE_ID` is documented in
`README.md`, `backend/README.md` and `backend/.env.example`, with
`DEFAULT_TENANT_ID` kept as a deprecated fallback in `backend/app/config.py`.
The frozen-storage mismatch is explained in `CLAUDE.md` § Data model and in
`docs/ARCHITECTURE.md`'s record table — those explanations are load-bearing, not
residue. `backend/tests/test_workspaces.py` pins both directions.

---

## D4 — Auth stays optional and local-first

**Decided:** 2026-08-25 · **Status:** executed

`AUTH_REQUIRED` unset is the **primary** mode, not a dev convenience: no API key,
default workspace, admin `local` user. API keys are the opt-in path for shared
deployments (a TA, a shared box).

Recorded because D1 changes what this seam *means*. It used to read as "SaaS mode
off"; it now reads as "the product's normal operating mode."

`docs/SECURITY.md` → "Production gaps" has been revisited under D1: the entries
about open tenant registration and public-API abuse protection are gone, since
there is no public multi-tenant API for them to describe. The ones about
credential handling, least-privilege IAM, and TLS stayed, and matter more.

**Consequences:** `docs/SECURITY.md` § Production gaps drops the entries about
open registration and public-API abuse protection. **`README.md` § Planned
hardening needed the same pass and did not get it** — it kept listing "WAF and
server-side quotas", the same concern under another name, until `db224df` a week
later. Nothing else in the docs survived that sweep, verified by
`git grep -inE "quota|plan limit|subscription|abuse|registration|multi-tenant|front door|stripe|billing|saas|waf|throttl" -- '*.md'`:
every remaining hit is historical text in this file, a different sense of the
word, or an affirmative post-D1 statement.

This entry's Status was originally recorded as "already true in code, no change
needed" — a description of the code and not of the two documents this decision
changed, which is why no consequences review was ever triggered. It moved to
`executed` only once the D9-tightened bar was met: `db224df` landed, both
documents were re-read against the entry, and the suite passed. D5 keeps that
original wording, because for D5 it is true.

---

## D5 — The demo build boundary holds

**Confirmed:** 2026-08-25 · **Status:** already true in code, no change needed

Two deployment surfaces, one codebase. The frontend picks between fixture data and
the real API at build time via the provider in `frontend/src/data/`; components
never import `api/client.js` directly. `make demo-bundle-check` asserts no API
client leaked into the demo bundle.

D1 makes this **more** load-bearing, not less — the public simulation is now half
the stated product rather than a marketing page.

**Consequences:** no code change. The boundary is held by
`frontend/scripts/check-demo-bundle.sh` in CI, `frontend/src/data/contract.d.ts`
at compile time, and `providerContract.test.js` at runtime, and described in
`README.md` § Try it and `CLAUDE.md`'s opening. **This is the half of D1's
docs-alignment delegation that held**, and it held because something enforces it.
The contrast with D4 is the whole argument for pinning a claim to a test wherever
one can exist (D9).

---

## D6 — The onboarding external ID is operator-generated, not platform-issued

**Decided:** 2026-08-31 · **Status:** executed

`deploy/cloudformation/scanner-role.yaml` requires an `ExternalId` parameter with
no default. The operator generates it (`make onboarding-id`), supplies it to the
stack, and supplies the same value again when registering the role ARN the stack
outputs. `POST /accounts` keeps `external_id` optional, for roles configured by
hand.

**Why this came up.** `docs/DEMO.md` claimed the external ID was "generated
server-side, so a third party who learns the role ARN still cannot assume it."
Nothing generated it — `AccountCreate.external_id` was an optional string the
caller supplied — so the claim described a protection the code did not provide.
Two ways to close that: build server issuance, or correct the claim.

**Why not server issuance.** It cannot be bolted onto `POST /accounts`: that
endpoint needs the role ARN, which does not exist until the stack has run, and
the stack needs the external ID as input. Making it real means a two-phase
onboarding — issue a pending enrollment, deploy the role, finalize with the ARN —
which is a state machine with expiry, reuse, and abandonment cases.

That is the right design for untrusted, self-service onboarding. This is not
that: `POST /accounts` is **admin-only** and the deployment is self-hosted, so
there is no untrusted actor who can point the platform at an arbitrary role ARN.
Server issuance here would prevent operator mistakes, not close an exploitable
path — and preserving a sentence is not a reason to build a state machine.

**What is guaranteed:** the role trusts exactly one platform role ARN (not an
account root — the template rejects one) and will not issue credentials without
the matching external ID.

**What is not:** platform-enforced uniqueness, non-reuse, or expiry of external
IDs; any proof that a submitted value came from `make onboarding-id`; any audit
trail of enrollment before the role exists. `make onboarding-id` buys entropy and
the convention that the operator assigns the value — not enforcement.

**Revisit when any of these becomes true:**

- account onboarding is opened to untrusted or self-service users
- more than one delegated operator can register accounts
- external-ID reuse across accounts is actually observed
- enrollment needs auditing *before* the role is created
- the deployment stops being single-operator and self-hosted (would reopen D1)

**Deferred design, so it is not re-derived:** issue and persist a pending
enrollment with a generated external ID → the account owner deploys the role →
finalize the registration with the resulting role ARN.

**Consequences:** `docs/DEMO.md`'s server-generated claim is retracted and its
trust-policy snippet now names a role rather than an account root;
`docs/SECURITY.md` gains § Onboarding an account, including what the external ID
does not do. No backend, API, or frontend change.

---

## D7 — The walkthrough fixtures are a separate, ephemeral, billable stack

**Decided:** 2026-09-01 · **Status:** executed

`deploy/cloudformation/lab-fixtures.yaml` creates the resources the scanner is
supposed to find, in a target account, driven by `deploy/lab-fixtures.sh`
(`up` / `status` / `down`). It is the only artifact in this repo that
deliberately costs money, it is never merged into the onboarding template, and
its canonical state between walkthroughs is **not deployed**.

Defaults create an unassociated Elastic IP, an unattached 1 GiB volume, a
t3.micro that `up` immediately stops, and an empty private bucket — $4.37/month
at rest. NAT Gateway, load balancer and RDS are each opt-in and default off.

**Why this came up.** `docs/DEMO.md` step 2 said "there is **no stack for
these**" and told the operator to build four resources by hand, then listed the
teardown as three account-wide `length()` checks. Every part of that was a
liability: hand-built fixtures are not reproducible, an account-wide count means
nothing in an account holding anything else, and the one project whose entire
thesis is "you forgot to shut something down" was relying on the operator
remembering to shut something down.

**Why the instance launches running.** CloudFormation cannot declare a stopped
instance; there is no `State` property on `AWS::EC2::Instance`. The alternatives
were a custom resource (a Lambda, an execution role, and a new failure mode, to
set one flag) or documenting the stop. Neither is good, so `up` owns the stop
instead — a step inside the command that always runs, rather than a line in a
document that gets skipped. The gap it closes is $11.96/month → $4.37/month.

**Why the severity spread survives the stop.** The unattached volume carries
MEDIUM whether or not the instance is running, so stopping it trades a MEDIUM
finding for a LOW one and keeps all four severities. The running instance was
buying $7.59/month of nothing. That is the whole argument, and it only became
visible once the resource set was written down.

**Why `down` verifies.** Teardown failures are silent — that is the premise of
the product. The check filters on `Purpose=lab-fixture` rather than counting the
account, so it names survivors and works in a shared account, and it looks for an
RDS snapshot as well as an instance: `AWS::RDS::DBInstance` defaults to
`DeletionPolicy: Snapshot`, so the default behaviour of the template would have
left a billed, `describe-db-instances`-invisible leftover after every teardown.
The template pins `Delete`; the script checks anyway.

**Why the prices are in the template as data.** `ShutItDownFixtureCost` in the
template metadata is machine-readable so `tests/test_lab_fixtures_template.py`
can recompute every figure from `app/pricing/static_prices.py`. A cost written in
a comment drifts the moment the price table changes, and this stack's one job is
to be honest about what it costs.

**Two figures were wrong until the stack was actually deployed** (2026-09-01,
all opt-ins, ~12 minutes, $0.019). Both are recorded because both were invisible
to a test that only compares the template against `static_prices.py`:

- The advertised ALB cost was $16.43, the hourly rate alone. An internet-facing
  ALB also gets a public IPv4 address AWS bills separately, visible in
  `describe-addresses` as an untagged, requester-managed allocation owned by
  `amazon-elb`. Enabling `--alb` costs $20.08. The scanner was right all along —
  it reports the balancer and its address as two findings; the template's
  aggregate was what lied.
- `lab-fixtures.sh status` quoted the $4.37 baseline regardless of which opt-ins
  were on, understating an all-opt-ins stack by $71/month. It now sums what is
  actually enabled, and the test pins the per-opt-in rates too.

**Considered and rejected:** folding the fixtures into `scanner-role.yaml` (that
template is what students run — the rule that it creates nothing billable is
worth more than one fewer file); using the account's default VPC (a deleted
default VPC breaks it, and the teardown stops being complete); enabling
everything by default (~$80/month standing, for a demo that gains one extra
severity); creating nothing by default (an elaborate no-op).

**Consequences:** `docs/DEMO.md` § 2 and § After recording rewritten around the
two commands; `deploy/README.md` gains § 3; `CLAUDE.md` records the two-template
split. No backend, API, or frontend change — the new test reads files off disk.

---

## D8 — The platform role's `sts:AssumeRole` is scoped by tag, not by name or account list

**Decided:** 2026-08-31 · **Status:** executed

`platform-role.yaml` allows `sts:AssumeRole` on any role carrying
`Project=shut-it-down-aws`, the tag `scanner-role.yaml` puts on every role it
creates. Verified against real AWS in both directions: a tagged scanner role
assumes; an untagged decoy that trusted the platform role was refused.

**Why not `"*"`:** it was, and it granted more than the published policy claimed.

**Why not a `ScannerRoleName` parameter.** One parameter means one name for the
whole class. Accommodating a target that overrode `RoleName` removes access to
every target still on the default — it cannot support a heterogeneous set at all.
Tag-scoping is *why* an overridden `RoleName` works.

**Why not a `CommaDelimitedList` of target account ids.** It needs a platform
redeploy per student, which fights self-service onboarding.

**The tag is a namespace guard, not an authorization boundary** — a target's
owner controls its own tags. The boundary stays where it was: the target's trust
policy plus its external ID (D6). The coupling is silent, so
`test_platform_role_template.py` pins both templates to the same tag string.

**Consequences:** the decision landed as `a05b872`, and this entry records it
after the fact — the rationale sat in that commit's message and nowhere a
decisions reader would look. What it changed:
`deploy/cloudformation/platform-role.yaml` is created with the tag-conditioned
`sts:AssumeRole` statement; `deploy/terraform/main.tf` moves `sts:AssumeRole`
out of its `"*"`-resource statement into a matching tag-conditioned one;
`docs/SECURITY.md` gains § The platform's own runtime role, and
`deploy/README.md` says which existing role hosted deployments attach the
policy to instead; `backend/tests/test_platform_role_template.py` is created to
pin both templates to the same tag string, supported by the
`policy_document_under()` helper in `backend/tests/conftest.py` and the
heading-anchored block selection in `backend/tests/test_onboarding_template.py`.

---

## D9 — Finished means every claim is checkable and true, not that a feature list ran out

**Decided:** 2026-09-01 · **Status:** executed

The done-line, so it is not re-derived every session:

1. The five gates pass — `make test`, `make lint`, the frontend tests, the
   typecheck, and `make demo-bundle-check`.
2. Every number, list, and capability claim in the docs is true, and pinned by a
   test wherever that is practical rather than by attention. The IAM policy, the
   fixture costs, the shared tag across both role templates, and the provider
   contract are already held this way.
3. Every seam has a recorded decision. D1–D8 cover them; this entry closes the
   last open one, which was this question.
4. Work that is not built is labelled as not built.

**Finished explicitly does not require** anything under README's *Planned
hardening* or *What's next*, the `docs/DEMO.md` walkthrough recording, or
production hardening. Those are labelled, not owed.

**Why:** D1 makes this a self-hosted portfolio proof-of-concept, and its feature
list is deliberately open-ended — `CLAUDE.md` ships three extension recipes (new
scanner, new cleanup action, new notifier) so that the list *can* grow. A
done-line defined by features therefore never arrives, and "it feels ready" is
not a line anyone can check. The line that does arrive is that nothing in the
repo says something a reader can verify and find false.

**What tipped it:** three self-contradictions were standing on the day this was
written. The README pinned a test count of 182 against a suite of 213; a
mitigation sentence in `docs/SECURITY.md` sat under `POST /notify` instead of the
cleanup blast-radius gap it answers; and — the one that matters — README's
*Planned hardening* still listed "WAF and server-side quotas" a week after D4
removed exactly that concern from `docs/SECURITY.md` as inapplicable to a tool
with no public multi-tenant API. D4 was marked executed against the code and
against one of the two docs it changed.

**Consequence for this file's Status rule.** The preamble says a Status reaches
`executed` once the full verification suite passes. That is necessary and not
sufficient: the suite cannot see a doc the decision touched and nobody re-read.
`executed` now also means every document the decision names has been re-read
against it.

**Three lists of unbuilt work exist on purpose. Do not merge them.** README's
*Planned hardening* says what a reviewer should not expect to find; README's
*What's next* says what would be built next and in what order; `docs/SECURITY.md`
§ Production gaps says what an operator must know before pointing this at real
AWS. They overlap because they answer different questions, and collapsing them
into one list loses two of the three answers.

**Consequences:** four contradictions closed — the README test count (`8bb48cc`),
the misplaced mitigation sentence in `docs/SECURITY.md` (`1daa113`),
`docs/img/README.md` turned from authoring scaffolding into a manifest
(`f9452dc`), and D4's README leftover (`db224df`). This file's preamble rule for
`executed` is tightened by the paragraph above, and every entry now carries a
`**Consequences:**` line naming the documents it touched — the mechanism whose
absence let D4's miss survive. `README.md`'s three unbuilt-work lists and
`docs/SECURITY.md` § Production gaps stay exactly as they are, deliberately.

---

## D10 — Publication is gated on an independent security review, and the reviewer is not Claude

**Decided:** 2026-09-01 · **Status:** executed

The repository stays private until an adversarial review passes. The reviewer is
Codex, via `/crosscheck`, alongside the repo's own `/security-review`. A second
Claude pass does not satisfy this: the blind spot being guarded against is one
shared with whatever wrote the code, so more depth from the same model buys
nothing that independence buys.

What the review must cover, and what already holds each claim up — so the review
checks these rather than re-deriving them:

| Claim | How it is held today |
| --- | --- |
| No secrets, tfstate, tfvars or `.env` in the tree | `.gitignore`, verified against `git ls-files` |
| …nor anywhere in history | `git log --all --diff-filter=A --name-only` over every commit — only `.env.example` and `.env.demo` have ever been added |
| No real AWS account identifiers | only reserved-range placeholders appear in `demo-data/`, the fixture generator, and the tests |
| The granted IAM policy is the published one | `test_onboarding_template.py` pins `scanner-role.yaml` against `docs/SECURITY.md` |
| Both role templates agree on the scoping tag | `test_platform_role_template.py` (D8) |
| The demo bundle carries no API client and no credential handling | `scripts/check-demo-bundle.sh`, run in CI |
| The seven cleanup gates hold, including the refusals | `tests/test_cleanup.py` |
| Nothing unpublished is reachable from the remote | `git ls-remote origin` returns `HEAD` and `refs/heads/main` only (D11) |

**What fails the review:** any row above regressing; a local-only ref reaching
the remote; or a doc claiming a protection the code does not provide. That last
one is not hypothetical — it is precisely what D6 had to retract.

**Why record this rather than just doing it:** "I looked at it and it seemed
fine" is not a gate, and it is not repeatable. Naming the rows makes the review
finite, and makes a second review a re-run rather than a fresh act of judgement.

**Consequences:** no code or documentation change from recording the gate
itself. The repository stays private until the rows above are checked, and D12
places this between D9 and the public flip. Every row is checkable today; the
last one by `git ls-remote origin` (D11).

**The review ran on 2026-09-01** — Codex over a clean clone of exactly the
publishable tree (tracked files + full history; local untracked state excluded),
four passes on one thread, alongside a Claude-side `/security-review` of the
remediation diff, which found nothing. First verdict: **FAIL**, three findings —
an unrevokable orphaned API key, refusals and post-mutation failures escaping
the audit guarantee, and `backend/README.md` denying mutation exists. All fixed
code-first (D13). The re-runs tightened the fix twice more (D13 records those
edges too). Final verdict at `6eb3ef9`: **PASS**, all eight rows and the
doc-claim clause. What remains of D12's sequence is the operator's: the flip
itself.

---

## D11 — The commit history needs no further rewrite; what was left was local

**Decided:** 2026-09-01 · **Status:** executed

No squash, reword, rebase or author rewrite before publication. The one rewrite
this repo needed already happened: it removed four automatically added commit
trailers and changed nothing else — the backup ref's tree was byte-identical to
the tip — and the remote only ever carried the rewritten history. `main` is
linear, one author identity throughout (the GitHub noreply address, which
attributes to the account without publishing a personal one), descriptive
subjects.

**Why not a cosmetic rewrite anyway.** The linear history is part of what the
repository shows, not noise to flatten — and a rewrite would orphan every place
this file cites a commit by SHA (D8 names `a05b872`; D10 records its verdict
against a tip).

**What was actually left, and is now done.** Three local-only refs held
superseded objects alive in the working clone — the rewrite's backup ref, and
two session-checkpoint refs, one still carrying a file D2 deleted. Git never
pushes these by default, which is why the remote was already clean, but they
are exactly what a `git push --mirror` or `--all` would publish. All three
deleted, reflogs expired, objects pruned.

**Consequences:** `git for-each-ref` now returns three refs — `main` and the two
the remote tracks. D10's last row became checkable in one command. `CLAUDE.md`
§ Conventions carries the author-identity rule (`51bc60e`), a consequence of
this entry: the convention only holds if every session applies it, and
`DECISIONS.md` is read on demand while `CLAUDE.md` loads every session.

---

## D12 — Publication is a sequence, and the irreversible step belongs to the operator

**Decided:** 2026-09-01 · **Status:** decided

The order, and why it is this order:

1. **D9 — the docs are true.** First, because a security review of a repository
   whose documents misdescribe it reviews something that does not exist.
2. **D10 — the independent review passes.**
3. **D11 — nothing unpublished is reachable from the remote.** Done.
4. **Flip the repository public.** The operator does this, never an agent.
5. **Portfolio site** — the repository link, the live demo, and the walkthrough
   recording once it exists.

**Step 4 is irreversible in practice.** A public repository can be cloned,
forked, and archived by third parties within minutes; making it private again
does not retract what was already taken. That is why it sits behind three gates
and why no agent performs it.

**The walkthrough does not gate step 4** (D9). It is a portfolio artifact, and
standing the AWS side back up to record it is `docs/DEMO.md` § Before you
record — which is also the reason the external ID has to be generated before the
role stack, not after.

**Why record a sequence that seems obvious:** it was not obvious enough to stop
the question "is this done?" from being asked, and each of these steps is
individually easy to do out of order. Reviewing before the docs are true, or
publishing before the review, both cost more to undo than to sequence.

**Consequences:** no code or documentation change. The repository's private
status becomes a gate with a defined exit rather than an open state, and the
walkthrough recording is explicitly decoupled from it. `docs/DEMO.md` remains the
procedure for standing the AWS side back up when that recording happens.

**Step 4 happened on 2026-09-01**, performed by the operator, with D9–D11
closed and D10's review passed. The public demo was redeployed the same day so
the published bundle matches the published source. What remains of the sequence
is step 5; the walkthrough stays decoupled (D9).

---

## D13 — The audit guarantee is delivered by the code, not scoped down in the docs

**Decided:** 2026-09-01 · **Status:** executed

D10's first run (reviewer: Codex) returned FAIL with three findings: user
deletion could strand a live API key with no revocation path; the admin-role
and env-flag refusals — and any mutation whose audit write failed afterwards —
escaped the "every attempt audited" guarantee; and `backend/README.md`'s opening
claimed no mutating actions exist at all. Each had a cheap docs-side fix
(weaken the claim); the code-side fix was chosen for all three, and the shape of
the two non-trivial ones was settled in one conferral round that converged with
two hardenings Codex added.

What was built:

- **Key-first deletion.** `delete_user` revokes the `APIKEY#` row before the
  `USERS#` row. The two writes are independent, and only this order fails safe:
  cut short, it leaves a listed user with a dead key and a working retry — the
  reverse left a key that authenticated forever, unrevokable because the retry
  404'd before reaching it.
- **Every cleanup gate lives in the service.** The route no longer checks the
  env flag or uses `require_admin`; it resolves the principal, and
  `cleanup_service.execute` runs role and flag as its first two audited gates
  (`forbidden`, `disabled`). Role stays ahead of flag on purpose — the order the
  route used to enforce — so a member's refusal never reveals whether cleanup is
  enabled.
- **Write-ahead audit for real mutations.** Before any `dry_run: false` action
  touches AWS, an `initiated` entry is persisted; if it cannot be, the action is
  refused (`audit_unavailable`, 503) — the initiated write *is* the pre-flight,
  so there is no check-then-act race. A store failure after the mutation returns
  the outcome to the caller and leaves the initiated row standing as
  outcome-unknown, logged at error level. The guarantee this buys is exact: **a
  persistence-enabled install never starts a mutation without durable evidence
  of intent.** Zero-config mode (persistence disabled) sits deliberately outside
  it — log-only records, like everything else that mode does.

**The re-run tightened all three.** D10's second pass found the guarantee's
edges rather than new ground: a DynamoDB `ClientError` (access denied,
throttling) is not `PersistenceUnavailable` and slipped both guarded audit
paths; the write-ahead claim read as unconditional while zero-config mode is
deliberately log-only; "no refusal can bypass the trail" overclaimed against
401s and malformed bodies, which resolve no workspace to audit under; and the
API-key lookup's eventually consistent read could authenticate a just-revoked
key one more time. The first and last are code fixes (`ClientError` caught
alongside `PersistenceUnavailable` in both guarded paths; `ConsistentRead=True`
on `resolve_api_key`); the middle two are the docs stating the decided scope
precisely.

**Deliberately not built:** idempotency keys / a full attempt state machine
(conditional writes so a client retry cannot mutate twice). The live
precondition re-check already blunts retries — stopping a stopped instance
no-ops, a released EIP and a deleted volume fail their preconditions. Revisit if
an action whose retry is not naturally idempotent ever enters the catalog, or if
reconciliation of outcome-unknown rows becomes a real operator task.

**Also rejected:** scoping the docs claim to "attempts that reach the service"
(abandons the guarantee for refusals the service *can* see; the claim stays
bounded by authentication regardless — a 401 or a malformed body resolves no
workspace to audit under, and the docs say so); auditing at the route layer
(splits the audit vocabulary across layers and puts business logic in routes);
a per-request user-row check in auth (closes orphaned keys generally, at the
cost of doubling reads on every authenticated request).

**Consequences:** `backend/app/repositories/user_repository.py` (delete order,
consistent-read key resolution), `backend/app/services/cleanup_service.py`
(gates, write-ahead, guarded terminal write), `backend/app/main.py` (route +
status map), and `backend/app/repositories/audit_repository.py` (`build_record`
extracted) carry the code; `backend/tests/test_cleanup.py` and `test_users.py`
pin the new behavior, with each injected-outage path parametrized over both an
unreachable store and a store error. `frontend/src/data/contract.d.ts` widens
the status union. Docs re-read against the change: `backend/README.md`'s
opening warning rewritten (the third finding), root `README.md` gate 7,
`docs/SECURITY.md` §§ Cleanup gates + Audit logging, and `CLAUDE.md` invariant 2.

---

## Template

```markdown
## D<n> — <the decision, as a sentence>

**Decided:** YYYY-MM-DD · **Status:** decided | executed | superseded by D<n>

<What was chosen.>

**Why:** <what made this ambiguous, and what tipped it>

**Consequences:** <what changes in code, docs, or scope>
```
