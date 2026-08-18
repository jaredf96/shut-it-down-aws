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
my own account" and "I built a multi-tenant control plane."

---

## Before you record

Everything is provisioned with Terraform and destroyed immediately afterward, so
the whole exercise costs cents.

```bash
cd deploy/terraform/sandbox      # walkthrough-only stack
terraform init
terraform apply                  # creates the target-account role + demo resources
```

The stack creates:

- **In the target account** — `ShutItDownScannerRole` with the nine read-only
  actions, a trust policy naming the platform account as principal, and a
  `sts:ExternalId` condition bound to the generated ID.
- **Demo resources worth finding** — an unassociated Elastic IP, an unattached
  EBS volume, a stopped instance with an attached volume, and (optional, the
  priciest) a NAT Gateway.
- **A budget alarm**, so a forgotten teardown pages you instead of surprising you.

Verify CloudTrail is on in the target account before recording — the assumed-role
event is the most convincing single frame in the video.

> **Tear down the moment you stop recording.** `terraform destroy`. The NAT
> Gateway is the expensive one; an Elastic IP and a 1 GiB volume are rounding
> errors, but they are not free.

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
  "Principal": { "AWS": "arn:aws:iam::<PLATFORM_ACCOUNT>:root" },
  "Action": "sts:AssumeRole",
  "Condition": { "StringEquals": { "sts:ExternalId": "<GENERATED_ID>" } }
}
```

Say: *"The customer creates this role themselves. We never hold their keys — the
external ID is generated server-side, so a third party who learns the role ARN
still cannot assume it."* (That is the confused-deputy problem, and it is exactly
what the external ID exists to prevent.)

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

```bash
terraform destroy
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
