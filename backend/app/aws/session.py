"""boto3 Session providers.

`default_session` uses the server's own credentials (local / single-account).
`session_for_account` assumes a cross-account IAM role via STS so the scanners
can read a registered account using temporary credentials.
"""

from __future__ import annotations

import boto3

from app.utils import default_region

_SESSION_NAME = "cloud-lab-cleanup"


def default_session() -> boto3.Session:
    return boto3.Session()


def session_for_account(account: dict) -> boto3.Session:
    """Assume the account's role and return a Session with temporary creds."""
    sts = boto3.client("sts", region_name=default_region())

    kwargs = {"RoleArn": account["role_arn"], "RoleSessionName": _SESSION_NAME}
    if account.get("external_id"):
        kwargs["ExternalId"] = account["external_id"]

    creds = sts.assume_role(**kwargs)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
