# Demo script

A ~10-minute walkthrough that tells the whole product story: scan → cost →
alerts → history/diff → teams → multi-account → safe cleanup → billing.

There are two tracks — follow the **UI** track for a live demo, or the **API**
track (curl) for a terminal/recording. They cover the same beats.

## Prerequisites

- **Read-only** AWS credentials configured (`aws configure`) for an account that
  has a few lab leftovers (a NAT Gateway, an unassociated Elastic IP, and an
  unattached EBS volume make the best demo).
- Python 3.10+ and Node 18+ (or Docker).
- Optional: `jq` for pretty curl output.

> Everything here is read-only until the explicit cleanup step, which is gated
> behind a flag and a dry-run.

## 0. Start it

**Docker (recommended — includes local DynamoDB so history/teams/billing work):**

```bash
docker compose up --build      # backend on :8000, table auto-created
cd frontend && npm install && npm run dev   # UI on :5173
```

**Or local with persistence:**

```bash
# terminal 1 — local DynamoDB
docker run -p 8001:8000 amazon/dynamodb-local

# terminal 2 — backend
cd backend && source .venv/bin/activate
export DYNAMODB_TABLE_NAME=cloud-lab-scans DYNAMODB_ENDPOINT_URL=http://localhost:8001 DYNAMODB_AUTO_CREATE=true
uvicorn app.main:app --reload --port 8000

# terminal 3 — frontend
cd frontend && npm run dev
```

Health check: `curl localhost:8000/health` → `"persistence_enabled": true`.

---

## 1. Scan + cost estimates (the core value)

**UI:** open http://localhost:5173, click **Run scan**. Point out:
- The **"~$X/mo"** fleet-total card and the per-resource **Est. $/mo** column.
- **Risk badges** (HIGH/MEDIUM/REVIEW/LOW) and the plain-English cost column.

**API:**
```bash
curl -s localhost:8000/scan | jq '{
  fleet_cost: .summary.estimated_monthly_cost,
  by_risk: .summary.by_risk_level,
  example: .resources[0] | {resource_type, risk_level, estimated_monthly_cost, cost_source}
}'
```

Talking point: *"It doesn't just list resources — it explains why each costs
money and roughly how much, so a beginner knows what to kill."*

## 2. Alerts ranked by spend

**UI:** the **⚠️ Alerts** panel at the top — a new billable resource or standing
high-risk resource shows up, costliest first, with severity colors.

**API:**
```bash
curl -s localhost:8000/scan | jq '.alerts[] | {severity, title, estimated_monthly_cost}'
```

Run the scan **twice** (UI: click Run scan again): the second scan compares
against the first, so a *newly appeared* HIGH resource becomes a **CRITICAL**
"new billable resource" alert.

## 3. Scan history & diffing

**UI:** the **Scan history** sidebar lists saved scans with **"vs previous"**
badges (`+2 −1 ~3`). Use the **Compare** bar to diff any two scans — added /
removed / changed (with `running → stopped`, risk transitions) is shown in full.

**API:**
```bash
curl -s localhost:8000/scans | jq '.scans[] | {created_at, resource_count, vs_previous}'
# grab two ids, then:
curl -s "localhost:8000/scans/diff?from_id=<OLDER>&to_id=<NEWER>" | jq '.summary'
```

Talking point: *"This is what turns a scanner into a monitoring tool — you can
see drift over time."*

## 4. Notifications (optional, ~30s)

Set a Slack webhook and re-scan:
```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ NOTIFY_ON_SCAN=true
# restart backend, then:
curl -s localhost:8000/scan | jq '.notifications'
```
The same alert objects land in Slack. Email works the same way via `SMTP_*`.

## 5. Teams & roles

```bash
# Create a tenant (returns an admin API key — shown once)
ADMIN=$(curl -s -X POST localhost:8000/tenants -H 'Content-Type: application/json' \
  -d '{"name":"CS101"}'); echo $ADMIN | jq
AKEY=$(echo $ADMIN | jq -r .api_key)

# Add a student (member)
curl -s -X POST localhost:8000/users -H "X-API-Key: $AKEY" \
  -H 'Content-Type: application/json' -d '{"name":"Student Jane","role":"member"}' | jq
MKEY=<member api_key from above>

# Member can view, but not manage:
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/users \
  -H "X-API-Key: $MKEY" -H 'Content-Type: application/json' -d '{"name":"x"}'   # 403
```

**UI:** with `VITE_API_KEY` set to the admin key, the **Team** panel shows the
roster; members see it read-only.

Talking point: *"Classroom-ready — a teacher is admin, students are members,
everyone shares the dashboard."*

## 6. Multi-account (per-student accounts)

```bash
# Register an AWS account by its cross-account read-only role ARN (admin only)
curl -s -X POST localhost:8000/accounts -H "X-API-Key: $AKEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Jane Sandbox","role_arn":"arn:aws:iam::111111111111:role/CloudLabReadOnly"}' | jq
```

Now `GET /scan` assumes each registered account's role, scans it, and **tags
every resource with its account**. In the UI, an **Account** column appears with
a per-account filter (the teacher's per-student view).

## 7. Safe guided cleanup (the careful part)

Show that it's **off by default**:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/cleanup/execute \
  -H "X-API-Key: $AKEY" -H 'Content-Type: application/json' \
  -d '{"action":"stop_ec2_instance","resource_id":"i-x","confirm_resource_id":"i-x","region":"us-east-1"}'
# 403 "Cleanup actions are disabled in this environment."
```

Enable it and **dry-run first** (nothing changes):
```bash
export ENABLE_CLEANUP_ACTIONS=true   # restart backend

curl -s -X POST localhost:8000/cleanup/execute -H "X-API-Key: $AKEY" \
  -H 'Content-Type: application/json' -d '{
    "action":"release_elastic_ip","resource_id":"<eipalloc-…>",
    "confirm_resource_id":"<eipalloc-…>","region":"us-east-1","dry_run":true}' | jq
# -> status: "dry_run", detail: "Would release unassociated Elastic IP …"
```

**UI:** the **🧹 Guided cleanup** panel — pick an action, type the resource ID
**twice** to confirm, keep "Dry run" checked, click **Preview**. The live
"Execute" button is red. Flip dry-run off only if you actually want to release
the (truly unused) EIP.

Show the **audit trail**:
```bash
curl -s localhost:8000/cleanup/audit -H "X-API-Key: $AKEY" | jq '.entries[] | {status, action, resource_id, dry_run, created_at}'
```

Talking point: *"Deletion is a confirmed, audited checklist — not one-click
automation. Terminating instances or deleting buckets isn't even on the menu."*

## 8. Billing & plan limits

```bash
curl -s localhost:8000/billing -H "X-API-Key: $AKEY" | jq '{plan, limits, usage}'
# Free plan caps AWS accounts at 1 — adding a second:
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/accounts -H "X-API-Key: $AKEY" \
  -H 'Content-Type: application/json' -d '{"name":"A2","role_arn":"arn:aws:iam::222222222222:role/R"}'
# 402 "AWS-account limit reached for your plan."

# Upgrade (dev mode, no Stripe), then it succeeds:
curl -s -X POST localhost:8000/billing/plan -H "X-API-Key: $AKEY" \
  -H 'Content-Type: application/json' -d '{"plan":"pro"}' | jq '{plan, limits}'
```

**UI:** the **Plan & usage** panel shows the plan, usage vs limits, and an
upgrade control (Stripe Checkout when configured, a plan switcher in dev).

Talking point: *"Free/Pro plans gated by per-tenant limits, billed through
Stripe — the SaaS shape is there."*

## 9. Wrap-up (10-second pitch)

> "It scans an AWS account read-only, tells you in plain English what's costing
> money and roughly how much, alerts you when something new shows up, remembers
> history so you can see drift, works across many accounts and a whole class of
> students, and lets you clean up the safe stuff through an audited, confirm-to-
> delete checklist — with Free/Pro billing built in."

---

### Reset between demos

If you used local DynamoDB in-memory (the compose default), just restart the
`dynamodb-local` container to wipe tenants/scans/audit. Real AWS resources are
untouched unless you ran a non-dry-run cleanup.
