"""The platform role template must keep matching the policy the docs publish.

Same problem as `test_onboarding_template.py`, other end of the trust: this is
the role the backend runs as, and `docs/SECURITY.md` § Least-privilege IAM
publishes what it may do. Two hand-maintained copies of one permission list
drift, and the failure is silent.

One coupling here is load-bearing in a way the scanned-account template's is
not. The platform's `sts:AssumeRole` grant is scoped by the `Project` tag that
`scanner-role.yaml` puts on every role it creates. Change that tag in one file
and not the other and nothing fails to deploy — every scan simply starts
returning AccessDenied, per account, in `account_errors`. The tests below pin
the two files to the same tag.

No AWS calls: this reads three files off disk.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.conftest import REPO_ROOT, policy_document_under

TEMPLATE_PATH = REPO_ROOT / "deploy" / "cloudformation" / "platform-role.yaml"
SCANNER_TEMPLATE_PATH = REPO_ROOT / "deploy" / "cloudformation" / "scanner-role.yaml"
TERRAFORM_PATH = REPO_ROOT / "deploy" / "terraform" / "main.tf"

HEADING = "### The platform's own runtime role"

# The cleanup catalog. The platform role is allowed to hold these in principle
# (guided cleanup runs as the platform), but this template is the *scanning*
# runtime and opts into none of them — see docs/SECURITY.md, "grant the rest
# only when you opt into the corresponding feature".
CLEANUP_ACTIONS = {"ec2:StopInstances", "ec2:ReleaseAddress", "ec2:DeleteVolume"}


@pytest.fixture(scope="module")
def template() -> dict:
    """The parsed template — full-form intrinsics, so plain `safe_load` reads it."""
    return yaml.safe_load(TEMPLATE_PATH.read_text())


@pytest.fixture(scope="module")
def statements(template: dict) -> dict[str, dict]:
    policies = template["Resources"]["PlatformRole"]["Properties"]["Policies"]
    assert len(policies) == 1, "one inline policy keeps the grant readable in the console"
    return {s["Sid"]: s for s in policies[0]["PolicyDocument"]["Statement"]}


@pytest.fixture(scope="module")
def published() -> dict[str, dict]:
    return {s["Sid"]: s for s in policy_document_under(HEADING)["Statement"]}


def test_every_published_statement_is_in_the_template(statements, published):
    assert set(statements) == set(published)


@pytest.mark.parametrize(
    "sid", ["AppTableAccess", "ReadOnlyScanning", "AssumeRegisteredScannerRoles"]
)
def test_statement_grants_exactly_the_published_actions(statements, published, sid):
    granted = statements[sid]["Action"]
    documented = published[sid]["Action"]
    assert sorted(_as_list(granted)) == sorted(_as_list(documented))
    assert statements[sid]["Effect"] == "Allow"


def test_scanning_actions_match_the_scanned_account_policy(statements):
    """The platform scans its own account in single-account mode.

    It must not need more permission to read its own account than a student's
    account grants to read theirs.
    """
    scanned = policy_document_under("### A scanned account")["Statement"][0]["Action"]
    assert sorted(statements["ReadOnlyScanning"]["Action"]) == sorted(scanned)


def test_the_role_cannot_mutate_a_scanned_account(statements):
    """Scanning never mutates AWS (CLAUDE.md invariant 1), including here."""
    scanning = statements["ReadOnlyScanning"]["Action"]
    assert not CLEANUP_ACTIONS & set(scanning)
    for action in scanning:
        verb = action.split(":", 1)[1]
        assert verb.startswith(("Describe", "List", "Get")), f"{action} is not a read"
    assert "*" not in "".join(scanning), "no wildcard actions — ec2:Describe* grants user data"


def test_ready_probe_permission_is_granted(statements):
    """`GET /ready` calls DescribeTable; without it the backend reports unready."""
    assert "dynamodb:DescribeTable" in statements["AppTableAccess"]["Action"]


def test_assume_role_is_scoped_by_the_tag_the_scanner_template_sets(statements, template):
    """The load-bearing coupling: one tag, two files, no deploy-time failure.

    A mismatch here does not break a deploy — it makes every registered account
    fail to scan, one AccessDenied at a time.
    """
    assume = statements["AssumeRegisteredScannerRoles"]
    condition = assume["Condition"]["StringEquals"]
    assert list(condition) == ["aws:ResourceTag/Project"]

    # The template refers to a parameter; resolve it to the value it defaults to.
    referenced = condition["aws:ResourceTag/Project"]
    assert referenced == {"Ref": "ScannerRoleTagValue"}
    tag_value = template["Parameters"]["ScannerRoleTagValue"]["Default"]

    scanner = yaml.safe_load(SCANNER_TEMPLATE_PATH.read_text())
    scanner_tags = scanner["Resources"]["ScannerRole"]["Properties"]["Tags"]
    assert {"Key": "Project", "Value": tag_value} in scanner_tags


def test_assume_role_is_not_an_unconditional_wildcard(statements):
    """`Resource: "*"` with no condition lets the platform assume anything.

    The grant is deliberately wide on resource and narrow on condition, because
    registered ARNs are not knowable when the policy is written.
    """
    assume = statements["AssumeRegisteredScannerRoles"]
    assert "Condition" in assume, "an unconditional sts:AssumeRole is the finding this fixes"


def test_terraform_emits_the_same_actions(statements):
    """deploy/terraform/main.tf is the other copy of this grant.

    Comments are stripped first: this file explains the wildcard it used to
    grant, and a naive substring search reads that explanation as the grant.
    """
    lines = TERRAFORM_PATH.read_text().splitlines()
    terraform = "\n".join(line for line in lines if not line.lstrip().startswith("#"))

    granted = statements["ReadOnlyScanning"]["Action"] + statements["AppTableAccess"]["Action"]
    for action in granted:
        assert f'"{action}"' in terraform, f"{action} missing from the Terraform policy"
    assert '"ec2:Describe*"' not in terraform, "the wildcard this template narrowed away"
    assert 'variable = "aws:ResourceTag/Project"' in terraform


def test_operator_principal_rejects_an_account_root(template):
    pattern = re.compile(template["Parameters"]["OperatorPrincipalArn"]["AllowedPattern"])
    assert pattern.match("arn:aws:iam::123456789012:role/MyOperatorRole")
    assert not pattern.match("arn:aws:iam::123456789012:root")


def test_table_name_cannot_smuggle_an_iam_wildcard(template):
    """`cloud-lab-*` in an ARN would widen the grant across tables."""
    pattern = re.compile(template["Parameters"]["TableName"]["AllowedPattern"])
    assert pattern.match("cloud-lab-scans")
    assert not pattern.match("cloud-lab-*")


def test_nothing_grants_alongside_the_inline_policy(template):
    """An equal action list is only least privilege if it is the whole grant."""
    properties = template["Resources"]["PlatformRole"]["Properties"]
    assert "ManagedPolicyArns" not in properties
    assert list(template["Resources"]) == ["PlatformRole"]


def test_role_arn_is_output_for_onboarding(template):
    assert template["Outputs"]["RoleArn"]["Value"] == {"Fn::GetAtt": ["PlatformRole", "Arn"]}


def _as_list(action) -> list[str]:
    return action if isinstance(action, list) else [action]
