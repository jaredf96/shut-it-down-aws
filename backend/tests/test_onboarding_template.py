"""The onboarding template must keep matching the policy the docs publish.

`docs/SECURITY.md` tells an operator exactly which permissions the scanner role
needs, and `deploy/cloudformation/scanner-role.yaml` is what actually creates
that role. Two hand-maintained copies of one permission list drift, and the
failure is silent: the doc keeps promising least privilege while the template
grants something else. These tests parse both and compare them.

They also pin the two properties the design depends on:

* the trust policy names the platform's role and requires the external ID, and
* the role can only read. `docs/DEMO.md` step 5 demonstrates defense in depth by
  showing IAM refuse a cleanup action against this role — a write permission
  added here would silently invalidate that demonstration.

No AWS calls: this reads two files off disk.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.conftest import REPO_ROOT, policy_document_under

TEMPLATE_PATH = REPO_ROOT / "deploy" / "cloudformation" / "scanner-role.yaml"

# The cleanup catalog, which this role must never be able to perform.
CLEANUP_ACTIONS = {"ec2:StopInstances", "ec2:ReleaseAddress", "ec2:DeleteVolume"}


@pytest.fixture(scope="module")
def template() -> dict:
    """The parsed template.

    Intrinsics are written in full form (`Ref:`, not `!Ref`) precisely so this
    is plain YAML; a short-form tag here would raise on safe_load, which is the
    intended signal to convert it rather than to add a custom loader.
    """
    return yaml.safe_load(TEMPLATE_PATH.read_text())


@pytest.fixture(scope="module")
def role_properties(template: dict) -> dict:
    return template["Resources"]["ScannerRole"]["Properties"]


@pytest.fixture(scope="module")
def scanning_statement(role_properties: dict) -> dict:
    policies = role_properties["Policies"]
    assert len(policies) == 1, "one inline policy keeps the grant readable in the console"
    statements = policies[0]["PolicyDocument"]["Statement"]
    assert len(statements) == 1
    return statements[0]


@pytest.fixture(scope="module")
def granted_actions(scanning_statement: dict) -> list[str]:
    return scanning_statement["Action"]


@pytest.fixture(scope="module")
def published_actions() -> list[str]:
    """The action list from the scanned-account policy in docs/SECURITY.md.

    Selected by heading. This used to take the first JSON block containing
    `ec2:DescribeRegions`, which bound to whichever policy appeared first in the
    document — and the platform role's policy, added later, contains that action
    too.
    """
    return policy_document_under("### A scanned account")["Statement"][0]["Action"]


def test_template_grants_exactly_the_published_policy(granted_actions, published_actions):
    assert sorted(granted_actions) == sorted(published_actions)
    assert len(granted_actions) == len(set(granted_actions)), "duplicate action in the template"


def test_role_can_only_read(granted_actions):
    """Nothing here may mutate the scanned account — see docs/DEMO.md step 5."""
    assert not CLEANUP_ACTIONS & set(granted_actions)
    for action in granted_actions:
        verb = action.split(":", 1)[1]
        assert verb.startswith(("Describe", "List", "Get")), f"{action} is not a read"
    assert "*" not in "".join(granted_actions), "no wildcard actions"


def test_nothing_grants_alongside_the_inline_policy(template, role_properties):
    """An equal action list is only least privilege if it is the whole grant.

    Comparing action lists reads one statement in one inline policy. A managed
    policy attached to the role, or a second `AWS::IAM::Policy` naming it, would
    widen this role without changing anything that comparison looks at — and
    `AdministratorAccess` attached here would pass an action-list check while
    handing the platform write access to the whole account.
    """
    assert "ManagedPolicyArns" not in role_properties
    assert list(template["Resources"]) == [
        "ScannerRole"
    ], "a second resource could grant permissions alongside the inline policy"


def test_the_scanning_statement_allows_rather_than_denies(scanning_statement):
    """`Effect: Deny` would pass an action-list comparison and break every scan."""
    assert scanning_statement["Effect"] == "Allow"
    assert scanning_statement["Resource"] == "*"


def test_trust_policy_names_the_platform_role_and_requires_the_external_id(role_properties):
    statements = role_properties["AssumeRolePolicyDocument"]["Statement"]
    assert len(statements) == 1
    statement = statements[0]

    # The principal is the platform's own role, not the account root: a root
    # principal delegates to every principal in that account.
    assert statement["Principal"] == {"AWS": {"Ref": "PlatformRoleArn"}}
    assert statement["Action"] == "sts:AssumeRole"
    assert statement["Condition"] == {"StringEquals": {"sts:ExternalId": {"Ref": "ExternalId"}}}


def test_platform_role_arn_parameter_rejects_an_account_root(template):
    pattern = re.compile(template["Parameters"]["PlatformRoleArn"]["AllowedPattern"])
    assert pattern.match("arn:aws:iam::123456789012:role/shut-it-down-backend")
    assert not pattern.match("arn:aws:iam::123456789012:root")


def test_external_id_is_required_and_not_echoed(template):
    parameter = template["Parameters"]["ExternalId"]
    assert parameter["NoEcho"] is True
    assert "Default" not in parameter, "a default external ID would be shared by every account"
    assert parameter["MinLength"] >= 16


def test_role_arn_is_output_for_registration(template):
    assert template["Outputs"]["RoleArn"]["Value"] == {"Fn::GetAtt": ["ScannerRole", "Arn"]}
