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
finding. They are provisioned separately, and only the first is automated.

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

```bash
aws cloudformation deploy \
  --profile target \
  --template-file deploy/cloudformation/scanner-role.yaml \
  --stack-name shut-it-down-onboarding \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      PlatformRoleArn=arn:aws:iam::<PLATFORM_ACCOUNT>:role/<BACKEND_ROLE> \
      ExternalId=<THE_GENERATED_ID>

aws cloudformation describe-stacks --profile target \
  --stack-name shut-it-down-onboarding \
  --query 'Stacks[0].Outputs' --output table
```

The `RoleArn` output is what gets registered in the dashboard, together with the
same external ID.

### 2. Resources worth finding — by hand, for now

There is **no stack for these**. Create them in the target account yourself: an
unassociated Elastic IP, an unattached EBS volume, a stopped instance with an
attached volume, and — optional, and by far the priciest — a NAT Gateway.

Set a budget alarm at the same time. A forgotten teardown should page you rather
than surprise you at the end of the month, and nothing here does that for you.

> Automating this as a separate, explicitly opt-in fixtures stack is the obvious
> next step. It is deliberately not folded into the onboarding template: that
> template is what students run, and it must never create anything that costs
> money.

Verify CloudTrail is on in the target account before recording — the assumed-role
event is the most convincing single frame in the video.

> **Tear down the moment you stop recording** — see [After recording](#after-recording).
> The NAT Gateway is the expensive one; an Elastic IP and a 1 GiB volume are
> rounding errors, but they are not free. The role costs nothing and is still
> worth deleting.

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
  "Principal": { "AWS": "arn:aws:iam::<PLATFORM_ACCOUNT>:role/<BACKEND_ROLE>" },
  "Action": "sts:AssumeRole",
  "Condition": { "StringEquals": { "sts:ExternalId": "<GENERATED_ID>" } }
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
shows the platform account as the caller and the temporary session as the actor.

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
# The role — free to leave, but leave nothing behind
aws cloudformation delete-stack --profile target --stack-name shut-it-down-onboarding

# The findable resources — release the EIP, delete the volume and NAT Gateway,
# terminate the instance. These are the ones that cost money.
```

Then confirm the account is actually clean — teardown failures are quiet and
expensive:

```bash
aws ec2 describe-addresses --profile target --query 'length(Addresses)'
aws ec2 describe-volumes   --profile target --query 'length(Volumes)'
aws ec2 describe-nat-gateways --profile target \
  --query "length(NatGateways[?State=='available'])"
```

All three should return `0`.
