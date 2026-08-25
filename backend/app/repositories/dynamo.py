"""Shared DynamoDB plumbing: table accessor + idempotent table creation.

The whole app uses a single table with prefixed partition keys:

    pk = "TENANT#<workspace_id>"    sk = <scan_id>     -> a saved scan
    pk = "ACCOUNTS#<workspace_id>"  sk = <account_id>  -> a registered AWS account
    pk = "USERS#<workspace_id>"     sk = <user_id>     -> a team member
    pk = "AUDIT#<workspace_id>"     sk = <entry_id>    -> a cleanup attempt
    pk = "APIKEY#<sha256(key)>"     sk = "#"           -> api key -> principal

Distinct prefixes keep these record types from colliding in one partition, so
scoping scans by workspace is just a different `pk` value — no schema change.

**`TENANT#` is a frozen legacy name, not an oversight.** The logical model was
renamed tenant -> workspace (D3); the stored prefixes were deliberately not,
because a self-hosted install keeps its data on its own infrastructure and a
migration would have to be idempotent, partial-failure-safe and tested on every
install — for a name no caller can see. The one stored `tenant_id` *attribute*
that reaches a caller is translated in `user_repository`.

Two behaviors live here so no repository has to repeat them:

1. **Local-endpoint credential isolation.** When the configured endpoint is a
   recognized local DynamoDB, the client is built with dummy credentials
   instead of the ambient AWS chain. Local DynamoDB accepts any credentials, so
   this keeps persistence zero-config and decoupled from the developer's real
   (possibly expired) AWS session.
2. **Error translation.** Connectivity/credential failures become
   `PersistenceUnavailable` so the API can answer 503 rather than leaking a 500.
"""

from __future__ import annotations

import functools
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app import config
from app.errors import PersistenceUnavailable
from app.utils import default_region

# Hosts we are willing to treat as a local DynamoDB. Deliberately a narrow
# allowlist: dummy credentials must never be sent to an arbitrary endpoint.
_LOCAL_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "dynamodb-local",  # the docker compose service name
    }
)

# Placeholder credentials for local DynamoDB, which validates their presence
# but not their value.
_LOCAL_CREDENTIALS = {
    "aws_access_key_id": "local",
    "aws_secret_access_key": "local",
}


def is_enabled() -> bool:
    return config.persistence_enabled()


def is_local_endpoint(endpoint_url: str | None) -> bool:
    """True if `endpoint_url` points at a DynamoDB we consider local."""
    if not endpoint_url:
        return False
    return (urlparse(endpoint_url).hostname or "").lower() in _LOCAL_HOSTS


def _resource():
    """Build the DynamoDB resource, isolating local endpoints from real creds."""
    endpoint_url = config.get_dynamodb_endpoint_url()
    kwargs: dict[str, object] = {
        "region_name": default_region(),
        "endpoint_url": endpoint_url,
    }
    if is_local_endpoint(endpoint_url):
        kwargs.update(_LOCAL_CREDENTIALS)
    return boto3.resource("dynamodb", **kwargs)


class _TranslatingTable:
    """Wraps a boto3 Table so infrastructure failures become domain errors.

    Only `BotoCoreError` (credentials, endpoint connectivity, timeouts) is
    translated. A `ClientError` means DynamoDB was reached and replied, so it
    passes through untouched for callers that handle specific codes.
    """

    def __init__(self, table):
        self._table = table

    def __getattr__(self, name):
        attr = getattr(self._table, name)
        if not callable(attr):
            return attr

        @functools.wraps(attr)
        def wrapped(*args, **kwargs):
            try:
                return attr(*args, **kwargs)
            except BotoCoreError as exc:
                raise PersistenceUnavailable(str(exc)) from exc

        return wrapped


def get_table():
    return _TranslatingTable(_resource().Table(config.get_table_name()))


def ping() -> None:
    """Cheap readiness probe: confirm the table is reachable and described.

    Raises `PersistenceUnavailable` if DynamoDB cannot be reached or the table
    does not exist.
    """
    name = config.get_table_name()
    if not name:
        raise PersistenceUnavailable("DYNAMODB_TABLE_NAME is not set")
    try:
        _resource().meta.client.describe_table(TableName=name)
    except BotoCoreError as exc:
        raise PersistenceUnavailable(str(exc)) from exc
    except ClientError as exc:
        raise PersistenceUnavailable(
            f"{exc.response['Error'].get('Code', 'ClientError')}: {exc}"
        ) from exc


def ensure_table() -> None:
    """Create the single app table if it does not already exist (idempotent)."""
    name = config.get_table_name()
    if not name:
        raise RuntimeError("DYNAMODB_TABLE_NAME is not set")

    try:
        table = _resource().create_table(
            TableName=name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceInUseException":
            return
        raise
    except BotoCoreError as exc:
        raise PersistenceUnavailable(str(exc)) from exc
