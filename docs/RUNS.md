# Recorded runs against real AWS

The docs state how long a scan takes and describe what the scanner found in a
real account. A number stated from memory drifts, and a run described without
its record cannot be checked, so this file holds the records those statements
rest on. Each timing is the scan's own log line or the commit that measured it,
never a progress bar; each event of the own-account run is a saved row or a
CloudTrail entry. Account ids, principals, source addresses and the encoded part
of an authorization failure are stripped.

## Scan timings

`scan_service` logs one line when a scan starts (`scan start: N region(s) across
M scanners`) and one when it ends (`scan done: N resource(s) in Ts`), in
`backend/app/services/scan_service.py`. The regions are whatever
`describe_regions` returns for the account at run time
(`backend/app/utils/aws_regions.py`); every run recorded here saw 17. The
scanners run one after another, the six regional ones each sweeping their
regions concurrently while S3 lists its buckets once, so the per-scanner lines
sum to the total.

### 2026-07-24 — 12.4 s, 17 regions, an empty account

Commit `6b6f608`, which parallelized the region sweeps, records the measurement
it was made for, on the maintainer's own account:

> Measured: full 17-region scan 12.4s (was ~90-115s).

The account held nothing the scanners report: every scan saved in the local
history that day holds 0 resources.

### 2026-09-09 — 14.05 s, 17 regions, cross-account into one lab account

The backend's log of a scan through the assumed scanner role into a lab account
carrying the `deploy/cloudformation/lab-fixtures.yaml` stack with its RDS
opt-in. Timestamps are the machine's local time (UTC−4). The line before these,
which names the assumed role, is left out because it carries the account id.

```
2026-09-09 08:30:48,064 INFO app.scan: scan start: 17 region(s) across 7 scanners
2026-09-09 08:30:50,867 INFO app.scan:   ec2              1 resource(s) in   2.80s
2026-09-09 08:30:52,533 INFO app.scan:   ebs              2 resource(s) in   1.67s
2026-09-09 08:30:54,307 INFO app.scan:   elastic-ips      1 resource(s) in   1.77s
2026-09-09 08:30:55,985 INFO app.scan:   nat-gateways     0 resource(s) in   1.68s
2026-09-09 08:30:59,762 INFO app.scan:   load-balancers   0 resource(s) in   3.78s
2026-09-09 08:31:01,478 INFO app.scan:   rds              1 resource(s) in   1.72s
2026-09-09 08:31:02,118 INFO app.scan:   s3               2 resource(s) in   0.64s
2026-09-09 08:31:02,118 INFO app.scan: scan done: 7 resource(s) in 14.05s
```

### 2026-09-14 — 17.40 s, the same account and fixtures

The scan recorded for the walkthrough (`docs/DEMO.md` § 3), same setup:

```
2026-09-14 17:48:18,127 INFO app.scan: scan start: 17 region(s) across 7 scanners
2026-09-14 17:48:21,428 INFO app.scan:   ec2              1 resource(s) in   3.30s
2026-09-14 17:48:22,961 INFO app.scan:   ebs              2 resource(s) in   1.53s
2026-09-14 17:48:24,685 INFO app.scan:   elastic-ips      1 resource(s) in   1.72s
2026-09-14 17:48:27,774 INFO app.scan:   nat-gateways     0 resource(s) in   3.09s
2026-09-14 17:48:32,056 INFO app.scan:   load-balancers   0 resource(s) in   4.28s
2026-09-14 17:48:35,185 INFO app.scan:   rds              1 resource(s) in   3.13s
2026-09-14 17:48:35,531 INFO app.scan:   s3               2 resource(s) in   0.35s
2026-09-14 17:48:35,531 INFO app.scan: scan done: 7 resource(s) in 17.40s
```

So: about 12 s for 17 regions when the account is empty, and 14 to 17 s
cross-account into one account holding a handful of resources. The progress bar
in the dashboard is paced, not measured; its elapsed counter is real, but the
figures to quote are these.

## 2026-07-10 — the own-account run, with a planted Elastic IP

The earliest run against the maintainer's own account (us-east-1) that the
local history still holds, from the morning durable local history landed
(`54b1130`). The account held nothing the scanners report, so the finding was
planted on purpose: an
Elastic IP allocated from the admin CLI, tagged `Name=scanner-canary-3`, to give
the scan, the history comparison, the alert rules, the cleanup gates and the IAM
backstop one real resource to act on, and released from the same CLI a few
minutes later. It was a canary. Nothing in this run had been forgotten. What
it cost is not in any record cited here: the address existed for 3 minutes
36 seconds, under a cent at the list rate the scanner prices it by, and no
billing record is cited. Two earlier canaries the same morning were scanned
before the store was durable and left no saved scan; CloudTrail holds their
allocation and release, all from the admin CLI: `scanner-canary` (with a 1 GiB
volume) allocated 08:13:03 and released 08:15:22, `scanner-canary-2` allocated
08:25:14 and released 08:27:41.

The sequence, in UTC. The scan and audit rows are the local history's
(dynamodb-local, table `cloud-lab-scans`, read on 2026-09-28). The CloudTrail
entries are the account's Event history in us-east-1, looked up by event name
on 2026-09-28; each is given with its event id. The two admin calls carry the
AWS CLI's user agent, the refused one boto3's, which is the backend's.

| Time | Event | Record |
| --- | --- | --- |
| 08:39:18 | Scan 1: 0 resources | scan `2026-07-10T08:39:18.608Z_3f8a3e49` |
| 08:39:34 | `aws ec2 allocate-address` from the admin CLI, tag `Name=scanner-canary-3` → `eipalloc-0adbceaf8847361ec` | CloudTrail `AllocateAddress`, event `6c7306f5-355e-40c7-b19f-80ae503b98c1` |
| 08:41:04 | Scan 2: 1 resource — Elastic IP `eipalloc-0adbceaf8847361ec`, `scanner-canary-3`, unassociated, HIGH, $3.65/mo at the static list price, "AWS charges hourly for every public IPv4 address, and this one is not even attached to a running resource." `+1` against scan 1 | scan `2026-07-10T08:41:04.722Z_de972464` |
| 08:42:43 | `release_elastic_ip`, dry run, with a confirmation id deliberately wrong → `confirmation_mismatch` | audit `2026-07-10T08:42:43.522Z_e98cbc64` |
| 08:42:44 | Dry run on an allocation id that does not exist → `precondition_failed` | audit `2026-07-10T08:42:44.627Z_1bd1601c` |
| 08:42:45 | Dry run on the canary → `dry_run`: "Would release unassociated Elastic IP eipalloc-0adbceaf8847361ec." | audit `2026-07-10T08:42:45.491Z_593e1f3e` |
| 08:42:46 | The same with `dry_run: false`: every gate in the app passed, the call reached EC2, and EC2 refused it. The backend's default credentials were the account's read-only SSO permission set, which grants no `ec2:ReleaseAddress` → `error`, detail `UnauthorizedOperation … no identity-based policy allows the ec2:ReleaseAddress action` | audit `2026-07-10T08:42:46.657Z_40565a4b`; CloudTrail `ReleaseAddress` at 08:42:46, error code `Client.UnauthorizedOperation`, event `96023559-382a-40ee-99b5-82ddf6c8cde1` |
| 08:43:10 | `aws ec2 release-address` from the admin CLI | CloudTrail `ReleaseAddress`, event `2d6ac7ba-c5be-4b86-9f8f-ce587a50dcd0` |
| 08:45:05 | Scan 3: 0 resources, `−1` against scan 2 | scan `2026-07-10T08:45:05.146Z_09183751` |

What the run shows: a real unassociated Elastic IP is found, priced at the
static list rate, ranked HIGH and explained in plain English; the saved history
carries it into one scan and out of the next; three refusals and a preview are
audited with their reasons; and the one real release attempt was stopped by IAM
after every gate in the app had let it through, because the credentials the
backend ran on granted no `ec2:ReleaseAddress`: the refusal at IAM rather than
in the app that `docs/SECURITY.md` § Least-privilege IAM describes, where
`ENABLE_CLEANUP_ACTIONS=true` grants nothing by itself. What it does not show: a
resource anyone had forgotten, or what the address was billed at. The canary
was planted and removed by hand inside the run.
