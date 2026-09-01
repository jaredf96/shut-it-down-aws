"""The fixtures template must keep telling the truth about what it costs.

`deploy/cloudformation/lab-fixtures.yaml` is the one artifact in this repo that
deliberately creates billable resources, so the properties worth pinning are the
ones that keep it honest and disposable:

* the advertised prices match `app/pricing/static_prices.py`, so the template's
  cost table cannot drift away from the numbers the dashboard reports;
* nothing billable is created unconditionally, and the expensive three default
  to off;
* every billable resource carries the tag `deploy/lab-fixtures.sh down` filters
  on — an untagged fixture is invisible to the teardown check, which is worse
  than no check at all;
* the database is deleted rather than snapshotted, because
  `AWS::RDS::DBInstance` defaults to `Snapshot` and a leftover snapshot is
  billed and invisible to `describe-db-instances`;
* it creates no IAM principal. That is `scanner-role.yaml`'s job, and the whole
  reason there are two templates is that students run that one and it must never
  create anything that costs money.

No AWS calls: this reads three files off disk.
"""

from __future__ import annotations

import re

import pytest
import yaml

from app.pricing.static_prices import (
    ALB_HOURLY,
    EBS_GB_MONTH,
    EC2_HOURLY,
    NAT_GATEWAY_HOURLY,
    PUBLIC_IPV4_HOURLY,
    RDS_HOURLY,
    RDS_STORAGE_GB_MONTH,
    monthly,
)
from tests.conftest import REPO_ROOT

TEMPLATE_PATH = REPO_ROOT / "deploy" / "cloudformation" / "lab-fixtures.yaml"
SCRIPT_PATH = REPO_ROOT / "deploy" / "lab-fixtures.sh"

# Resource types that appear on a bill. Everything else the template creates —
# the VPC, its subnets, the gateway, the route table, a security group, a DB
# subnet group — is free, which is why none of it is gated.
BILLABLE_TYPES = {
    "AWS::EC2::EIP",
    "AWS::EC2::Volume",
    "AWS::EC2::Instance",
    "AWS::EC2::NatGateway",
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::RDS::DBInstance",
}

# The free scaffolding, which is created unconditionally on purpose: gating a
# $0 resource on whichever billable fixture happens to need it buys nothing and
# makes the conditions compound.
FREE_NETWORK_TYPES = {
    "AWS::EC2::VPC",
    "AWS::EC2::Subnet",
    "AWS::EC2::InternetGateway",
    "AWS::EC2::VPCGatewayAttachment",
    "AWS::EC2::RouteTable",
    "AWS::EC2::Route",
    "AWS::EC2::SubnetRouteTableAssociation",
}

FIXTURE_TAG = ("Purpose", "lab-fixture")


@pytest.fixture(scope="module")
def template() -> dict:
    """The parsed template.

    Intrinsics are written in full form (`Ref:`, not `!Ref`) so this is plain
    YAML, matching scanner-role.yaml. A short-form tag here would raise on
    safe_load, which is the intended signal to convert it rather than to add a
    custom loader.
    """
    return yaml.safe_load(TEMPLATE_PATH.read_text())


@pytest.fixture(scope="module")
def resources(template: dict) -> dict:
    return template["Resources"]


@pytest.fixture(scope="module")
def parameters(template: dict) -> dict:
    return template["Parameters"]


@pytest.fixture(scope="module")
def cost_metadata(template: dict) -> dict:
    return template["Metadata"]["ShutItDownFixtureCost"]


def _tags(properties: dict) -> dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in properties.get("Tags", [])}


# --- what it costs ----------------------------------------------------------


def test_advertised_prices_match_the_backends_own_price_table(cost_metadata):
    """The cost table is the template's central claim; recompute all of it.

    A comment claiming "$3.65" drifts silently the moment static_prices.py
    changes. These are the same numbers the dashboard will report for the very
    resources this stack creates, so a mismatch means the template is lying to
    the operator about the thing it exists to be careful about.
    """
    stopped_root = round(EBS_GB_MONTH["gp3"] * 8, 2)

    assert cost_metadata["Resources"] == {
        "IdleAddress": monthly(PUBLIC_IPV4_HOURLY),
        "OrphanVolume": round(EBS_GB_MONTH["gp3"] * 1, 2),
        "LabInstanceStopped": stopped_root,
        "LabInstanceRunning": round(monthly(EC2_HOURLY["t3.micro"]) + stopped_root, 2),
        "NatGateway": round(monthly(NAT_GATEWAY_HOURLY) + monthly(PUBLIC_IPV4_HOURLY), 2),
        "LoadBalancer": monthly(ALB_HOURLY),
        "Database": round(monthly(RDS_HOURLY["db.t3.micro"]) + 20 * RDS_STORAGE_GB_MONTH, 2),
        "ArtifactBucket": 0.0,
    }


def test_the_totals_are_the_sum_of_what_is_on_by_default(cost_metadata):
    """Both headline figures describe the same stack, before and after the stop.

    The gap between them is the entire reason `up` stops the instance rather
    than leaving it to a documented afterthought.
    """
    per_resource = cost_metadata["Resources"]
    default_on = per_resource["IdleAddress"] + per_resource["OrphanVolume"]

    assert cost_metadata["Totals"]["DeployedBaseline"] == round(
        default_on + per_resource["LabInstanceStopped"] + per_resource["ArtifactBucket"], 2
    )
    assert cost_metadata["Totals"]["RunningRateEquivalent"] == round(
        default_on + per_resource["LabInstanceRunning"] + per_resource["ArtifactBucket"], 2
    )


def test_the_script_quotes_the_same_rates_as_the_template(cost_metadata):
    """`lab-fixtures.sh` prints these at the operator; they must be the same two."""
    script = SCRIPT_PATH.read_text()
    quoted = {
        name: float(re.search(rf'^{name}="([\d.]+)"$', script, re.MULTILINE).group(1))
        for name in ("RATE_DEPLOYED_BASELINE", "RATE_RUNNING_EQUIVALENT")
    }
    assert quoted["RATE_DEPLOYED_BASELINE"] == cost_metadata["Totals"]["DeployedBaseline"]
    assert quoted["RATE_RUNNING_EQUIVALENT"] == cost_metadata["Totals"]["RunningRateEquivalent"]


# --- what it creates, and when ----------------------------------------------


def test_nothing_billable_is_created_unconditionally(resources):
    """Deploying with no parameters must not be able to surprise anyone.

    Asserted from the unconditional side rather than by listing the billable
    resources: a new fixture added without a condition fails this even if
    nobody remembers to add its type to BILLABLE_TYPES.
    """
    unconditional = {
        name: body["Type"] for name, body in resources.items() if "Condition" not in body
    }
    assert (
        set(unconditional.values()) <= FREE_NETWORK_TYPES
    ), f"created unconditionally and not free: {unconditional}"


def test_the_expensive_fixtures_default_to_off(parameters):
    for name in ("CreateNatGateway", "CreateLoadBalancer", "CreateDatabase"):
        assert parameters[name]["Default"] == "false", f"{name} must be opt-in"
        assert parameters[name]["AllowedValues"] == ["true", "false"]


def test_the_cheap_fixtures_default_to_on(parameters):
    """A stack that creates nothing by default would be an elaborate no-op."""
    for name in (
        "CreateIdleAddress",
        "CreateOrphanVolume",
        "CreateLabInstance",
        "CreateArtifactBucket",
    ):
        assert parameters[name]["Default"] == "true"


def test_every_billable_resource_carries_the_teardown_tag(resources):
    """`lab-fixtures.sh down` filters its post-delete check on this tag.

    An untagged billable resource is invisible to that check, which is worse
    than having no check: the teardown would report clean while still billing.
    """
    key, value = FIXTURE_TAG
    for name, body in resources.items():
        if body["Type"] not in BILLABLE_TYPES:
            continue
        assert _tags(body["Properties"]).get(key) == value, f"{name} is untagged"


def test_the_database_is_deleted_not_snapshotted(resources):
    """AWS::RDS::DBInstance defaults to DeletionPolicy: Snapshot.

    Inheriting that default leaves a billed snapshot behind after every
    teardown — and one that `describe-db-instances` does not report, so the
    survivor check would not see it either.
    """
    database = resources["Database"]
    assert database["DeletionPolicy"] == "Delete"
    assert database["UpdateReplacePolicy"] == "Delete"
    assert database["Properties"]["BackupRetentionPeriod"] == 0, "automated backups are storage"


def test_stateful_resources_do_not_outlive_the_stack(resources):
    """Anything with a retain-flavoured default gets an explicit Delete."""
    for name in ("OrphanVolume", "ArtifactBucket", "Database"):
        assert resources[name]["DeletionPolicy"] == "Delete"
        assert resources[name]["UpdateReplacePolicy"] == "Delete"


def test_the_bucket_is_private(resources):
    """It is empty and disposable, but this is a project about least privilege."""
    block = resources["ArtifactBucket"]["Properties"]["PublicAccessBlockConfiguration"]
    assert all(block.values()), block


def test_the_fixtures_stack_creates_no_iam(resources):
    """Permissions live in scanner-role.yaml; fixtures live here.

    Collapsing the two would put billable resources in the template a student
    runs, which is the one thing that template must never do.
    """
    iam = {name: body["Type"] for name, body in resources.items() if "::IAM::" in body["Type"]}
    assert not iam, f"the fixtures stack must not create principals: {iam}"


def test_the_instance_declares_its_own_root_volume(resources, parameters, cost_metadata):
    """The root volume is the entire cost of the stopped instance.

    Inheriting it from whichever AMI the SSM parameter resolves to today would
    make LabInstanceStopped a guess rather than a figure.
    """
    root = resources["LabInstance"]["Properties"]["BlockDeviceMappings"][0]["Ebs"]
    assert root["VolumeType"] == "gp3"
    assert root["DeleteOnTermination"] is True
    assert root["VolumeSize"] == {"Ref": "RootVolumeSizeGb"}

    assert cost_metadata["Resources"]["LabInstanceStopped"] == round(
        EBS_GB_MONTH["gp3"] * parameters["RootVolumeSizeGb"]["Default"], 2
    )


def test_the_database_password_has_no_working_default(parameters):
    """A working default password in a published template is worth more to an
    attacker than this fixture is to anyone."""
    password = parameters["DatabasePassword"]
    assert password["NoEcho"] is True
    assert password["Default"] == "", "an empty default fails the stack rather than creating one"


def test_no_hardcoded_ami(parameters):
    """A literal AMI id is region-specific and goes stale."""
    assert parameters["LatestAmiId"]["Type"] == "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>"
    assert parameters["LatestAmiId"]["Default"].startswith("/aws/service/ami-")
