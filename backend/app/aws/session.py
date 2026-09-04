"""boto3 Session providers.

`default_session` uses the server's own credentials (local / single-account).
`session_for_account` assumes a cross-account IAM role via STS so the scanners
can read a registered account using temporary credentials.

The assumed session is **named after the principal that caused it**
(`shutitdown.<workspace>.<user>`), because that string is what the *scanned*
account's own CloudTrail records: every event there arrives as
`assumed-role/<RoleName>/<session name>`. One constant made every call from
every user of every workspace indistinguishable in the one log that account's
owner actually reads. The name is asserted by this caller, not proven — see
docs/SECURITY.md and D18 for what that does and does not buy.
"""

from __future__ import annotations

import hashlib
import re

import boto3

from app.utils import default_region

# IAM allows 2-64 characters from [\w+=,.@-] in a RoleSessionName.
_MAX_SESSION_NAME = 64
_PREFIX = "shutitdown"  # so an account's owner can recognise the tool
_UID_LIMIT = 32  # a uuid4 hex; never truncated in practice
_DIGEST = 6
_SAFE = re.compile(r"[A-Za-z0-9_-]+")
_UNATTRIBUTED = f"{_PREFIX}.unattributed"


def _segment(value: str, limit: int) -> str:
    """One field of the session name: the literal value, or a marked shortening.

    "." separates the fields and "=" marks a shortened one; neither can occur
    inside a field, so the name always splits back into its parts and a value
    that was truncated or sanitised can never be read as a literal one. The
    digest is over the whole original, so two ids sharing a prefix stay
    distinct.
    """
    value = value or "unknown"
    if len(value) <= limit and _SAFE.fullmatch(value):
        return value
    head = value[: max(limit - _DIGEST - 1, 1)]
    head = "".join(c if _SAFE.fullmatch(c) else "-" for c in head)
    return f"{head}={hashlib.sha256(value.encode()).hexdigest()[:_DIGEST]}"


def session_name_for(principal: dict | None) -> str:
    """`shutitdown.<workspace>.<user>` — what the scanned account's trail shows.

    The user field is never shortened away: it is the only one that has to
    resolve to exactly one person. The workspace field gets whatever of the
    64-character budget the user field leaves.
    """
    if not principal:
        return _UNATTRIBUTED
    user = _segment(str(principal.get("user_id") or ""), _UID_LIMIT)
    budget = _MAX_SESSION_NAME - len(_PREFIX) - 2 - len(user)
    workspace = _segment(str(principal.get("workspace_id") or ""), budget)
    return f"{_PREFIX}.{workspace}.{user}"


def default_session() -> boto3.Session:
    return boto3.Session()


def session_for_account(account: dict, *, principal: dict | None = None) -> boto3.Session:
    """Assume the account's role and return a Session with temporary creds.

    `principal` is attribution only: it names the session so the *scanned*
    account's CloudTrail shows who caused each call. It changes nothing about
    what is granted. Omitted (a caller with no request behind it), the session
    is named honestly unattributed rather than borrowing an identity.
    """
    sts = boto3.client("sts", region_name=default_region())

    kwargs = {"RoleArn": account["role_arn"], "RoleSessionName": session_name_for(principal)}
    if account.get("external_id"):
        kwargs["ExternalId"] = account["external_id"]

    creds = sts.assume_role(**kwargs)["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
