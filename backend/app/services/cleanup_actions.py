"""The (deliberately narrow) catalog of supported cleanup actions.

Only low-risk lab cleanup is supported:

  - stop_ec2_instance          stop (NOT terminate) a running instance — reversible
  - release_elastic_ip         release an UNASSOCIATED Elastic IP
  - delete_unattached_ebs_volume   delete an AVAILABLE (unattached) volume — destructive

Each action re-checks its precondition against live AWS state at execution time
(never trusting the client), and supports `dry_run` to report what *would*
happen without mutating anything. Explicitly out of scope: terminating EC2,
deleting S3 buckets, deleting RDS, deleting NAT Gateways (warning-only).
"""

from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError


class PreconditionError(Exception):
    """Raised when live state means the action must not proceed."""


def _describe_or_fail(call, label: str):
    try:
        return call()
    except (BotoCoreError, ClientError) as exc:
        raise PreconditionError(f"{label}: {exc}") from exc


def _stop_ec2_instance(session, region: str, resource_id: str, dry_run: bool) -> str:
    ec2 = session.client("ec2", region_name=region)
    resp = _describe_or_fail(
        lambda: ec2.describe_instances(InstanceIds=[resource_id]),
        f"Instance {resource_id} not found in {region}",
    )
    reservations = resp.get("Reservations", [])
    instances = reservations[0]["Instances"] if reservations else []
    if not instances:
        raise PreconditionError(f"Instance {resource_id} not found in {region}.")
    state = instances[0]["State"]["Name"]
    if state != "running":
        raise PreconditionError(f"Instance is '{state}', not 'running' — nothing to stop.")

    if dry_run:
        return f"Would stop running instance {resource_id} (reversible)."
    ec2.stop_instances(InstanceIds=[resource_id])
    return f"Stopped instance {resource_id}. You can start it again later."


def _release_elastic_ip(session, region: str, resource_id: str, dry_run: bool) -> str:
    ec2 = session.client("ec2", region_name=region)
    resp = _describe_or_fail(
        lambda: ec2.describe_addresses(AllocationIds=[resource_id]),
        f"Elastic IP {resource_id} not found in {region}",
    )
    addresses = resp.get("Addresses", [])
    if not addresses:
        raise PreconditionError(f"Elastic IP {resource_id} not found in {region}.")
    if addresses[0].get("AssociationId"):
        raise PreconditionError(
            "Elastic IP is associated with a running resource — refusing to release."
        )

    if dry_run:
        return f"Would release unassociated Elastic IP {resource_id}."
    ec2.release_address(AllocationId=resource_id)
    return f"Released Elastic IP {resource_id}."


def _delete_unattached_ebs_volume(session, region: str, resource_id: str, dry_run: bool) -> str:
    ec2 = session.client("ec2", region_name=region)
    resp = _describe_or_fail(
        lambda: ec2.describe_volumes(VolumeIds=[resource_id]),
        f"Volume {resource_id} not found in {region}",
    )
    volumes = resp.get("Volumes", [])
    if not volumes:
        raise PreconditionError(f"Volume {resource_id} not found in {region}.")
    state = volumes[0]["State"]
    if state != "available":
        raise PreconditionError(
            f"Volume is '{state}', not 'available' (unattached) — refusing to delete."
        )

    if dry_run:
        return f"Would delete unattached volume {resource_id} (irreversible data loss)."
    ec2.delete_volume(VolumeId=resource_id)
    return f"Deleted unattached volume {resource_id}."


# Supported actions. `run(session, region, resource_id, dry_run) -> detail str`.
ACTIONS: dict[str, dict] = {
    "stop_ec2_instance": {
        "resource_type": "EC2 Instance",
        "verb": "Stop",
        "destructive": False,
        "reversible": True,
        "description": "Stop a running instance to halt compute charges.",
        "run": _stop_ec2_instance,
    },
    "release_elastic_ip": {
        "resource_type": "Elastic IP",
        "verb": "Release",
        "destructive": True,
        "reversible": False,
        "description": "Release an unassociated Elastic IP to stop hourly charges.",
        "run": _release_elastic_ip,
    },
    "delete_unattached_ebs_volume": {
        "resource_type": "EBS Volume",
        "verb": "Delete",
        "destructive": True,
        "reversible": False,
        "description": "Delete an unattached (available) volume. The data cannot be recovered.",
        "run": _delete_unattached_ebs_volume,
    },
}

# Documented, intentionally NOT automated yet — surfaced so the UI is transparent.
NOT_SUPPORTED: list[dict] = [
    {
        "resource_type": "NAT Gateway",
        "reason": "Warning-only for now — delete manually in the console.",
    },
    {
        "resource_type": "EC2 Instance",
        "reason": "Termination is not automated — only Stop is supported.",
    },
    {
        "resource_type": "S3 Bucket",
        "reason": "Bucket deletion is not automated (data-loss risk).",
    },
    {
        "resource_type": "RDS Database",
        "reason": "Database deletion is not automated (data-loss risk).",
    },
]


def catalog() -> list[dict]:
    """Public metadata for the supported actions (no callables)."""
    return [
        {k: v for k, v in {"key": key, **spec}.items() if k != "run"}
        for key, spec in ACTIONS.items()
    ]
