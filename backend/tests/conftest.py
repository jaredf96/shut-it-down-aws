"""Shared pytest fixtures and AWS infra helpers.

All AWS calls are intercepted by moto, so these tests never touch a real
account and need no real credentials.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"

REPO_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DOC = REPO_ROOT / "docs" / "SECURITY.md"

_HEADING = re.compile(r"^#{1,6} .*$", re.MULTILINE)
_JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)


def policy_document_under(heading: str) -> dict:
    """The first fenced JSON policy block under `heading` in docs/SECURITY.md.

    Anchored to the heading, not to the block's contents. The drift tests used
    to take the first block containing a known action, which meant a second
    policy added anywhere above the intended one silently rebound them to the
    wrong policy — a test that still passes while pinning nothing.
    """
    text = SECURITY_DOC.read_text()
    headings = [(match.start(), match.group().strip()) for match in _HEADING.finditer(text)]
    for index, (position, line) in enumerate(headings):
        if line != heading:
            continue
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        blocks = _JSON_BLOCK.findall(text[position:end])
        assert blocks, f"no JSON policy block under {heading!r} in docs/SECURITY.md"
        return json.loads(blocks[0])
    raise AssertionError(f"heading {heading!r} not found in docs/SECURITY.md")


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Fake credentials so boto3 never reads your real ~/.aws during tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_REGION", REGION)


@pytest.fixture(autouse=True)
def mocked_aws(aws_credentials):
    """Wrap every test in moto's in-memory AWS mock."""
    with mock_aws():
        yield


@pytest.fixture(autouse=True)
def single_region(monkeypatch):
    """Pin region discovery to one region so tests are fast and deterministic.

    Each scanner imported `get_regions` into its own namespace, and the scan
    service now resolves regions once for the whole aggregate scan, so we patch
    the reference on every module that uses it.
    """
    from app.scanners import (
        ebs_scanner,
        ec2_scanner,
        elastic_ip_scanner,
        load_balancer_scanner,
        nat_gateway_scanner,
        rds_scanner,
    )
    from app.services import scan_service

    for module in (
        ec2_scanner,
        ebs_scanner,
        elastic_ip_scanner,
        nat_gateway_scanner,
        load_balancer_scanner,
        rds_scanner,
        scan_service,
    ):
        monkeypatch.setattr(module, "get_regions", lambda session=None: [REGION])


@pytest.fixture
def dynamo_table(monkeypatch):
    """Enable persistence and create the scan-history table under moto.

    Not autouse: only the persistence tests opt in, so other tests keep
    running with persistence disabled (the default).
    """
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "test-scans")
    from app.repositories import scan_repository

    scan_repository.ensure_table()
    return "test-scans"


# --- Infra helpers -------------------------------------------------------


def make_vpc_with_subnets(num_subnets: int = 1):
    """Create a VPC and one or more subnets (each in a distinct AZ).

    Returns (ec2_client, vpc_id, [subnet_ids]).
    """
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
    subnet_ids = []
    for i in range(num_subnets):
        subnet = ec2.create_subnet(
            VpcId=vpc_id,
            CidrBlock=f"10.0.{i + 1}.0/24",
            AvailabilityZone=azs[i % len(azs)],
        )
        subnet_ids.append(subnet["Subnet"]["SubnetId"])
    return ec2, vpc_id, subnet_ids
