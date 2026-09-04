"""Request models for account + user management endpoints.

Accounts/users are persisted as plain DynamoDB items (see the repositories);
these pydantic models validate the request bodies that create them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# A role ARN, and nothing else. `aws[a-z-]*` keeps aws-cn and aws-us-gov
# working; `.+` allows a role path (role/path/To/Name). Anchored, because the
# account id is parsed back out of this string and stored as the record's
# primary key — a value that only *contains* an ARN would key the record on
# whatever twelve digits appeared first.
#
# `[0-9]`, not `\d`: `\d` matches every Unicode decimal digit, so an ARN
# written with Arabic-Indic numerals validated and then became the record's
# sort key. That is worse than the malformed input this pattern exists to
# reject, because it looks like it worked.
_ROLE_ARN = r"^arn:aws[a-z-]*:iam::[0-9]{12}:role/.+$"


class AccountCreate(BaseModel):
    name: str
    role_arn: str = Field(pattern=_ROLE_ARN)
    external_id: str | None = None
    regions: list[str] | None = None  # None -> auto-discover for that account


class UserCreate(BaseModel):
    name: str
    role: str = "member"  # "admin" | "member"
