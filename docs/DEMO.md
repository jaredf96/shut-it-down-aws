# Cross-account sandbox walkthrough

The recording script for the ~90-second video that proves the AWS integration is
real. The [public demo](../README.md#-try-it) runs on fixtures so anyone can
click it safely; this is the counterpart that shows the live path.

**What it proves**, in order of how much a reviewer cares:

1. A real cross-account **trust policy** in a second AWS account.
2. A **generated external ID**, required by that trust policy.
3. A real **`sts:AssumeRole`** producing temporary credentials.
4. **Account tagging** — findings labeled with the account they came from.
5. **CloudTrail** showing the assumed-role session acting in the target account.
6. **Isolation** — the platform account is not the thing being scanned.

Point 6 is the one worth lingering on. It is the difference between "I scanned
my own account" and "I built a control plane that scans accounts it is not in."

---

## Before you record

Two things have to exist in the target account: the role, and something worth
finding. Each has its own stack, and they stay separate on purpose — the role
costs nothing and the fixtures cost money.

### 1. The role — the same stack a student runs

Nothing walkthrough-specific here. This is
[`deploy/cloudformation/scanner-role.yaml`](../deploy/cloudformation/scanner-role.yaml),
the onboarding template an instructor hands out, which is part of why the
walkthrough is worth recording: the reviewer watches the real onboarding path.

Generate the external ID **first** — the stack takes it as input, so it cannot
be issued after the fact:

```bash
make onboarding-id            # keep this value; you need it twice
```

Substitute the bare `UPPERCASE` placeholders before running. They are not
written as `<PLACEHOLDER>` on purpose — `<` is a shell redirect, so a bracketed
one fails with a syntax error mid-recording.

```bash
aws cloudformation deploy \
  --profile target \
  --template-file deploy/cloudformation/scanner-role.yaml \
  --stack-name shut-it-down-onboarding \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      PlatformRoleArn=arn:aws:iam::PLATFORM_ACCOUNT:role/shut-it-down-backend \
      ExternalId=THE_GENERATED_ID

aws cloudformation describe-stacks --profile target \
  --stack-name shut-it-down-onboarding \
  --query 'Stacks[0].Outputs' --output table
```

The `RoleArn` output is what gets registered in the dashboard, together with the
same external ID.

### 2. Resources worth finding — the fixtures stack

[`deploy/cloudformation/lab-fixtures.yaml`](../deploy/cloudformation/lab-fixtures.yaml)
creates the leftovers, driven by
[`deploy/lab-fixtures.sh`](../deploy/lab-fixtures.sh):

```bash
deploy/lab-fixtures.sh up target
```

That deploys the stack and then **stops the instance**, which is not a tidy-up
step — it is what takes the stack from $11.96/month to $4.37/month.
CloudFormation cannot declare a stopped instance, so `up` owns the stop rather
than leaving it to a line in this file that would get skipped.

What you get, and what each one is for:

| Fixture | Reported as | Rate |
| --- | --- | --- |
| Unassociated Elastic IP | HIGH | $3.65/mo |
| Unattached 1 GiB gp3 volume | MEDIUM | $0.08/mo |
| Stopped instance + 8 GiB root | LOW | $0.64/mo |
| Empty private bucket | REVIEW | $0 |

Four severities out of one stack. The unattached volume is what carries MEDIUM,
which is why stopping the instance costs the demo nothing.

The expensive three are **off by default** and opt in one at a time — pass
`--nat` ($36.50/mo, and that is a floor: the backend does not price NAT data
processing at all), `--alb` ($20.08/mo), or `--rds` ($14.71/mo, and it needs
`LAB_FIXTURES_DB_PASSWORD` in the environment). Enable them for a recording,
not for a standing test bed.

Every figure above is pinned against `backend/app/pricing/static_prices.py` by
`tests/test_lab_fixtures_template.py`, so the template cannot quietly start
lying about what it costs. They are also monthly *rates*, not what a recording
costs — an hour at the baseline is under a cent. The rate only becomes a bill if
the stack is left standing.

A budget alarm is still worth having, but it is no longer the only thing between
you and a surprise: `down` verifies (see [After recording](#after-recording)).

Verify CloudTrail is on in the target account before recording — the assumed-role
event is the most convincing single frame in the video.

> **The fixtures stack is ephemeral.** Between walkthroughs, the canonical state
> is that it does not exist. `deploy/lab-fixtures.sh status target` will tell you
> which it is.

---

## The script

### 1. Show there is nothing up your sleeve (~10s)

```bash
aws sts get-caller-identity --profile platform
```

Say: *"This is the platform account. It runs the scanner. It is not the account
we are about to scan."*

### 2. Show the trust policy in the target account (~15s)

Display the role's trust relationship — the platform account as principal, plus
the external-ID condition:

```json
{
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::PLATFORM_ACCOUNT:role/shut-it-down-backend" },
  "Action": "sts:AssumeRole",
  "Condition": { "StringEquals": { "sts:ExternalId": "THE_GENERATED_ID" } }
}
```

Say: *"The student creates this role themselves — we never hold their keys. It
trusts one specific role in the platform account, not the account as a whole, and
it will not hand out credentials without an external ID the instructor issued per
account."*

Both halves matter, and the principal is the load-bearing one. The external ID is
**not** a secret that makes a role ARN safe to publish — knowing an ARN never
granted anyone the right to assume it. Narrowing the principal is what limits who
may try; the external ID is what stops a confused deputy from being talked into
trying on someone else's behalf.

### 3. Register the account and scan (~25s)

In the dashboard, add the account, then run a scan. What to point at on screen:

- The **ACCOUNT** column — findings tagged by source account.
- The **account filter** — switch between accounts.
- The cost summary and risk ranking updating.

Say: *"One scan, fanned out across every enabled region concurrently, tagging
each finding with the account it came from."*

### 4. Show the assume-role actually happened (~20s)

Two pieces of evidence, ideally side by side:

```bash
# Application log: the STS session the scanner opened
grep AssumeRole <backend log>
```

Then CloudTrail **in the target account**, filtered to `AssumeRole`. The event
shows the platform account as the caller and the temporary session as the actor
— and the session name says *which user*: `shutitdown.<workspace>.<user>`.

Say: *"Temporary credentials, scoped to a read-only role, in an account whose
keys I do not have."*

### 5. Show the read-only guarantee is enforced outside the app (~20s)

With cleanup enabled, attempt a mutating action against the scanner role:

```
502  UnauthorizedOperation: not authorized to perform ec2:ReleaseAddress
```

Say: *"Every in-app safety gate passed — admin, typed confirmation, dry-run
disabled, live precondition re-check — and IAM still refused, because the scanner
role has no write permissions. Cleanup requires a separate role that this
deployment does not have."*

This is the strongest twenty seconds available: it demonstrates defense in depth
with a real refusal rather than a claim.

### 6. Close (~10s)

Say: *"The public demo you can click is fixture data, by design. This is the
live path, and the two are deployed separately so an anonymous visitor never
reaches anything that can assume a role."*

---

## After recording

Two teardowns, because there were two setups:

```bash
# The findable resources — these are the ones that cost money
deploy/lab-fixtures.sh down target

# The role — free to leave, but leave nothing behind
aws cloudformation delete-stack --profile target --stack-name shut-it-down-onboarding
```

`down` empties the bucket, deletes the stack, and then **re-checks**, because
teardown failures here are quiet and expensive. It finds survivors by the
`Purpose=lab-fixture` tag rather than by an account-wide count, so it names what
is left instead of reporting that some number is not zero, and it works in an
account that holds other things. It also looks for an RDS *snapshot*: an
`AWS::RDS::DBInstance` defaults to `DeletionPolicy: Snapshot`, and a leftover
snapshot is billed and invisible to `describe-db-instances`.

**A failed teardown is a failed command** — `down` exits non-zero and prints
what is still standing. Do not read a clean exit as optimism; it is a checked
claim. Re-run it after deleting anything it named.

To check the account without deleting anything:

```bash
deploy/lab-fixtures.sh status target
```
