"""Request models for account + user management endpoints.

Accounts/users are persisted as plain DynamoDB items (see the repositories);
these pydantic models validate the request bodies that create them.
"""

from __future__ import annotations

from pydantic import BaseModel


class AccountCreate(BaseModel):
    name: str
    role_arn: str
    external_id: str | None = None
    regions: list[str] | None = None  # None -> auto-discover for that account


class UserCreate(BaseModel):
    name: str
    role: str = "member"  # "admin" | "member"
