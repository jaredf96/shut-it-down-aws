#!/usr/bin/env bash
# Shut It Down — lifecycle for the billable walkthrough fixtures.
#
#   deploy/lab-fixtures.sh up     <aws-profile> [--nat] [--alb] [--rds] [--keep-running]
#   deploy/lab-fixtures.sh down   <aws-profile>
#   deploy/lab-fixtures.sh status <aws-profile>
#
# All three take an optional --region; without it the profile's own region is
# used, and a profile with no region configured is an error rather than a guess.
#
# The fixtures stack is ephemeral by design. Between walkthroughs the canonical
# state is that it does not exist, so this script is the intended way to touch
# it: `up` creates it and immediately stops the instance, `down` deletes it and
# then CHECKS, rather than trusting the delete.
#
# That check is the point. docs/DEMO.md warns that teardown failures here are
# quiet and expensive, and a project whose whole thesis is "you forgot to shut
# something down" cannot leave its own fixtures running. `down` exits non-zero
# and names the survivors if anything is left, so a failed teardown is a failed
# command rather than a surprise on next month's bill.
#
# `up` does not record the walkthrough — a person does that. The two halves are
# separate commands so the recording can take as long as it takes.
set -euo pipefail

STACK_NAME="shut-it-down-lab-fixtures"
FIXTURE_TAG="lab-fixture"
DB_IDENTIFIER="shut-it-down-lab-postgres"
ALB_NAME="shut-it-down-lab-alb"

# Monthly rates in USD, quoted so `up` can say what it just started charging.
# These are duplicated from the template's ShutItDownFixtureCost metadata, which
# in turn mirrors backend/app/pricing/static_prices.py.
# tests/test_lab_fixtures_template.py pins every one of them against that
# metadata — do not edit one of them alone.
RATE_DEPLOYED_BASELINE="4.37"
RATE_RUNNING_EQUIVALENT="11.96"
RATE_NAT_GATEWAY="36.50"
RATE_LOAD_BALANCER="20.08"
RATE_DATABASE="14.71"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$ROOT/deploy/cloudformation/lab-fixtures.yaml"

usage() {
  cat >&2 <<'EOF'
Usage:
  deploy/lab-fixtures.sh up     <aws-profile> [--nat] [--alb] [--rds] [--keep-running]
  deploy/lab-fixtures.sh down   <aws-profile>
  deploy/lab-fixtures.sh status <aws-profile>

Options (all commands): --region REGION
  --nat / --alb / --rds   add the expensive fixtures; each is off by default
  --keep-running          skip the instance stop, to show the MEDIUM running case
  --rds also needs LAB_FIXTURES_DB_PASSWORD in the environment
EOF
  exit 2
}

COMMAND="${1:-}"
PROFILE="${2:-}"
[[ -n "$COMMAND" && -n "$PROFILE" ]] || usage
shift 2

WANT_NAT="false"
WANT_ALB="false"
WANT_RDS="false"
KEEP_RUNNING="false"
REGION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --nat) WANT_NAT="true" ;;
    --alb) WANT_ALB="true" ;;
    --rds) WANT_RDS="true" ;;
    --keep-running) KEEP_RUNNING="true" ;;
    --region)
      REGION="${2:-}"
      [[ -n "$REGION" ]] || usage
      shift
      ;;
    *) echo "unknown option: $1" >&2; usage ;;
  esac
  shift
done

# No default profile and no default region. Guessing either means acting on
# whatever account and region happen to be configured — the same reason
# deploy-demo.sh refuses to invent a profile.
if [[ -z "$REGION" ]]; then
  REGION="$(aws configure get region --profile "$PROFILE" 2>/dev/null || true)"
fi
if [[ -z "$REGION" ]]; then
  echo "Profile '$PROFILE' has no region configured; pass --region REGION." >&2
  exit 2
fi

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }

# Resolved once, in an assignment, so `set -e` aborts on a failure here. Worked
# out inside a probe's arguments it would be evaluated before the probe ran,
# and a failed STS call would silently yield a bucket name with an empty
# account id — a check that passes by looking for the wrong thing.
ACCOUNT_ID="$(aws_ sts get-caller-identity --query Account --output text)"
BUCKET_NAME="shut-it-down-lab-fixtures-${ACCOUNT_ID}-${REGION}"

stack_exists() {
  aws_ cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1
}

# Present only while the stack is; empty rather than an error once it is gone.
stack_output() {
  aws_ cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text 2>/dev/null || true
}

# --- inventory --------------------------------------------------------------

# One survivor check. A probe that FAILS is reported as a finding rather than
# swallowed: an expired token, a denied permission or a wrong region would
# otherwise turn "I could not look" into "nothing is there". That is the exact
# substitution this whole project exists to catch — scanners raise instead of
# returning [] for the same reason — and it would be doing it inside its own
# teardown check.
# `--output text` separates rows with newlines and columns with tabs; flattening
# both leaves a trailing separator that showed up as a ragged space on every
# reported line.
_oneline() { echo "$1" | tr '\t\n' '  ' | sed 's/  */ /g; s/ *$//'; }

probe() {
  local label="$1"
  shift
  local out
  if ! out="$("$@" 2>&1)"; then
    printf 'CHECK FAILED (%s): %s\n' "$label" "$(_oneline "$out")"
    return 0
  fi
  if [[ -n "${out//[[:space:]]/}" ]]; then
    printf '%s: %s\n' "$label" "$(_oneline "$out")"
  fi
}

# Everything billable this stack can create, found by tag rather than by an
# account-wide count. DEMO.md's old teardown check counted every address and
# volume in the account, which only means something in an account holding
# nothing else. Naming a survivor is also more useful than reporting that some
# number is not zero.
#
# Each probe prints a line or nothing, so an empty result is a positive claim:
# every check ran and found nothing.
find_fixtures() {
  probe "Elastic IP" aws_ ec2 describe-addresses \
    --filters "Name=tag:Purpose,Values=$FIXTURE_TAG" \
    --query 'Addresses[].AllocationId' --output text

  probe "EBS volume" aws_ ec2 describe-volumes \
    --filters "Name=tag:Purpose,Values=$FIXTURE_TAG" \
    --query 'Volumes[].VolumeId' --output text

  probe "EC2 instance" aws_ ec2 describe-instances \
    --filters "Name=tag:Purpose,Values=$FIXTURE_TAG" \
    --query "Reservations[].Instances[?State.Name!='terminated'].[InstanceId,State.Name]" \
    --output text

  # --filter, singular. The plural spelling every other ec2 describe uses is
  # rejected by describe-nat-gateways.
  probe "NAT Gateway" aws_ ec2 describe-nat-gateways \
    --filter "Name=tag:Purpose,Values=$FIXTURE_TAG" \
    --query "NatGateways[?State!='deleted'].NatGatewayId" --output text

  probe "Load balancer" aws_ elbv2 describe-load-balancers \
    --query "LoadBalancers[?LoadBalancerName=='$ALB_NAME'].LoadBalancerArn" --output text

  probe "RDS instance" aws_ rds describe-db-instances \
    --query "DBInstances[?DBInstanceIdentifier=='$DB_IDENTIFIER'].DBInstanceIdentifier" \
    --output text

  # The template pins DeletionPolicy: Delete on the database precisely because
  # AWS::RDS::DBInstance defaults to Snapshot. A snapshot is billed and does not
  # appear in describe-db-instances, so it is exactly the leftover that would
  # otherwise go unnoticed. This call answers empty, not an error, when the
  # instance itself is gone.
  probe "RDS snapshot" aws_ rds describe-db-snapshots --db-instance-identifier "$DB_IDENTIFIER" \
    --query 'DBSnapshots[].DBSnapshotIdentifier' --output text

  # list-buckets rather than head-bucket: head-bucket fails identically for
  # "absent" and "denied", which would make a permissions problem look like a
  # clean teardown.
  probe "S3 bucket (free)" aws_ s3api list-buckets \
    --query "Buckets[?Name=='$BUCKET_NAME'].Name" --output text

  # Free, and expected while the stack stands. After a delete it is the signal
  # that the delete did not finish — which is why it is listed at all.
  probe "VPC (free)" aws_ ec2 describe-vpcs \
    --filters "Name=tag:Purpose,Values=$FIXTURE_TAG" \
    --query 'Vpcs[].VpcId' --output text
}

# --- up ---------------------------------------------------------------------

cmd_up() {
  if [[ "$WANT_RDS" == "true" && -z "${LAB_FIXTURES_DB_PASSWORD:-}" ]]; then
    echo "--rds needs LAB_FIXTURES_DB_PASSWORD set in the environment." >&2
    echo "It is passed as a NoEcho parameter and nothing ever connects to the" >&2
    echo "database, so any 8+ character alphanumeric throwaway will do." >&2
    exit 2
  fi

  echo "==> Deploying $STACK_NAME into $REGION"
  echo "    NAT Gateway: $WANT_NAT   load balancer: $WANT_ALB   database: $WANT_RDS"

  aws_ cloudformation deploy \
    --template-file "$TEMPLATE" \
    --stack-name "$STACK_NAME" \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
      "CreateNatGateway=$WANT_NAT" \
      "CreateLoadBalancer=$WANT_ALB" \
      "CreateDatabase=$WANT_RDS" \
      "DatabasePassword=${LAB_FIXTURES_DB_PASSWORD:-}"

  local instance
  instance="$(stack_output LabInstanceId)"

  if [[ -n "$instance" && "$KEEP_RUNNING" != "true" ]]; then
    # CloudFormation cannot declare a stopped instance, so this is the step
    # that takes the stack from the running rate down to the baseline. It runs
    # inside `up` rather than as a documented afterthought, because an
    # afterthought is the thing that gets skipped.
    echo "==> Stopping $instance — running is not the intended resting state"
    aws_ ec2 stop-instances --instance-ids "$instance" \
      --query 'StoppingInstances[0].CurrentState.Name' --output text
    aws_ ec2 wait instance-stopped --instance-ids "$instance"
    echo "    stopped"
  elif [[ -n "$instance" ]]; then
    echo "==> Leaving $instance RUNNING (--keep-running)"
  fi

  echo
  local checked=0
  cmd_status || checked=$?
  echo
  echo "Record the walkthrough, then tear it down:"
  echo "    deploy/lab-fixtures.sh down $PROFILE"
  return "$checked"
}

# --- status -----------------------------------------------------------------

# Decimal addition, because the rate is the one number here that must not be
# rounded into a reassuring shape.
_add() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.2f", a + b }'; }

_enabled() { echo "$1" | grep -q "^$2[[:space:]]*true"; }

# What the stack is actually charging, given which opt-ins are on. Quoting the
# baseline alone here understated an all-opt-ins stack by $71/month — in a tool
# whose entire subject is unnoticed spend.
print_rate() {
  local params="$1"
  local stopped="$RATE_DEPLOYED_BASELINE" running="$RATE_RUNNING_EQUIVALENT" extra=""

  if _enabled "$params" CreateNatGateway; then
    stopped="$(_add "$stopped" "$RATE_NAT_GATEWAY")"
    running="$(_add "$running" "$RATE_NAT_GATEWAY")"
    extra+=" + NAT Gateway \$$RATE_NAT_GATEWAY"
  fi
  if _enabled "$params" CreateLoadBalancer; then
    stopped="$(_add "$stopped" "$RATE_LOAD_BALANCER")"
    running="$(_add "$running" "$RATE_LOAD_BALANCER")"
    extra+=" + load balancer \$$RATE_LOAD_BALANCER"
  fi
  if _enabled "$params" CreateDatabase; then
    stopped="$(_add "$stopped" "$RATE_DATABASE")"
    running="$(_add "$running" "$RATE_DATABASE")"
    extra+=" + database \$$RATE_DATABASE"
  fi

  echo
  echo "Rate: \$$stopped/mo as configured, instance stopped."
  echo "      \$$running/mo if it is left running."
  if [[ -n "$extra" ]]; then
    echo "      baseline \$$RATE_DEPLOYED_BASELINE$extra"
  fi
  echo "NAT data processing and S3 storage are unpriced, so both are floors."
}

cmd_status() {
  local params=""
  if stack_exists; then
    echo "Stack $STACK_NAME in $REGION: PRESENT"
    params="$(aws_ cloudformation describe-stacks --stack-name "$STACK_NAME" \
      --query "Stacks[0].Parameters[?starts_with(ParameterKey, 'Create')].[ParameterKey,ParameterValue]" \
      --output text)"
    echo "$params" | sed 's/^/    /'
  else
    echo "Stack $STACK_NAME in $REGION: absent — the canonical state between walkthroughs"
  fi

  echo
  echo "Fixtures standing now (tagged Purpose=$FIXTURE_TAG):"
  local standing
  standing="$(find_fixtures)"
  if [[ -z "$standing" ]]; then
    echo "    none — every check ran and found nothing"
    return 0
  fi

  echo "$standing" | sed 's/^/    /'
  if echo "$standing" | grep -qv '^CHECK FAILED'; then
    print_rate "$params"
  fi
  # A check that could not run is a failed command here too, not a footnote.
  if echo "$standing" | grep -q '^CHECK FAILED'; then
    return 1
  fi
  return 0
}

# --- down -------------------------------------------------------------------

cmd_down() {
  # Derived rather than read from the stack wherever it can be: the check that
  # matters most runs after the stack has already been deleted.
  local bucket
  bucket="$(stack_output ArtifactBucketName)"
  if [[ -z "$bucket" ]]; then bucket="$BUCKET_NAME"; fi

  if [[ -n "$(aws_ s3api list-buckets --query "Buckets[?Name=='$bucket'].Name" --output text)" ]]; then
    # Nothing writes to this bucket, so it should already be empty.
    # CloudFormation refuses to delete a bucket that is not, and finding that
    # out during the delete costs a rollback.
    echo "==> Emptying s3://$bucket"
    aws_ s3 rm "s3://$bucket" --recursive --only-show-errors
  fi

  if stack_exists; then
    echo "==> Deleting $STACK_NAME"
    aws_ cloudformation delete-stack --stack-name "$STACK_NAME"
    aws_ cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
    echo "    deleted"
  else
    echo "==> $STACK_NAME is already absent; checking anyway"
  fi

  echo "==> Verifying nothing survived"
  local survivors
  survivors="$(find_fixtures)"

  if [[ -z "$survivors" ]]; then
    echo "    clean: no fixture resources remain"
    return 0
  fi

  echo >&2
  echo "TEARDOWN NOT VERIFIED CLEAN — survivors, or checks that could not run:" >&2
  echo "$survivors" | sed 's/^/    /' >&2
  echo >&2
  echo "Delete them by hand, then re-run: $0 down $PROFILE" >&2
  return 1
}

case "$COMMAND" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  *) usage ;;
esac
