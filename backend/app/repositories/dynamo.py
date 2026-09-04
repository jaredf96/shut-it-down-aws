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

Three behaviors live here so no repository has to repeat them:

1. **Local-endpoint credential isolation.** When the configured endpoint is a
   recognized local DynamoDB, the client is built with dummy credentials
   instead of the ambient AWS chain. Local DynamoDB accepts any credentials, so
   this keeps persistence zero-config and decoupled from the developer's real
   (possibly expired) AWS session.
2. **Error translation.** Connectivity/credential failures become
   `PersistenceUnavailable` so the API can answer 503 rather than leaking a 500.
   `ParamValidationError` is excluded — it means *we* built a bad request, and
   reporting our own bug as an unreachable backend sends the operator off to
   check DynamoDB.
3. **Pagination.** `query_items` follows `LastEvaluatedKey`. DynamoDB caps a
   Query at 1 MB of items read and reports the cut with a continuation key; a
   caller that ignores it gets a short page indistinguishable from an
   exhausted partition. Every repository read goes through it.
"""

from __future__ import annotations

import functools
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError

from app import config
from app.errors import PersistenceUnavailable, ResultSetTooLarge
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

# Pagination budget, in round trips per read. A Query with no FilterExpression
# always returns at least one item, so a read with a `limit` needs at most
# `limit` pages by construction and cannot loop: for those the budget is the
# limit itself, and `/scans` and `/cleanup/audit` bound theirs at the route.
# This floor is what covers the *unbounded* reads — accounts and users — where
# 25 pages is ~25 MB of 300-byte rows, far outside any workspace this is for.
_MAX_PAGES = 25


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
    translated, and `ParamValidationError` is excluded from that: it is raised
    client-side because *we* built a malformed request. A `ClientError` means
    DynamoDB was reached and replied, so it passes through untouched for
    callers that handle specific codes.
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
            except ParamValidationError:
                # We built a malformed request. That is our bug, not the
                # store's: let it surface as a loud 500 rather than a 503 that
                # sends the operator to check DynamoDB. (`Limit=0`, from an
                # unbounded `?limit=` query string, was reaching callers as
                # "Persistence backend is unavailable.")
                raise
            except BotoCoreError as exc:
                raise PersistenceUnavailable(str(exc)) from exc

        return wrapped

    def query_items(self, *, limit: int | None = None, **kwargs) -> list[dict]:
        """Query, following `LastEvaluatedKey`, and return the items.

        DynamoDB caps a Query at 1 MB of items *read* — before any
        `ProjectionExpression`, so projecting saves bandwidth, not pages — and
        reports the cut with a `LastEvaluatedKey`. A caller that ignores it
        gets a short page indistinguishable from an exhausted partition:
        "couldn't see" rendered as "nothing there".

        `limit` counts items *returned*, filled across pages. That is not
        DynamoDB's `Limit`, which caps how far a single request scans forward;
        passing `Limit` yourself is refused so the two cannot be confused.

        Error handling is `query`'s, unchanged: this calls the wrapped method,
        so `BotoCoreError` becomes `PersistenceUnavailable`, `ClientError`
        still passes through untouched mid-pagination, and a malformed request
        still raises `ParamValidationError`.
        """
        if "Limit" in kwargs or "ExclusiveStartKey" in kwargs:
            raise TypeError("query_items owns Limit/ExclusiveStartKey; pass limit=")
        if limit is not None and limit <= 0:
            return []

        # A page always carries at least one item (no read uses a
        # FilterExpression), so a bounded read terminates in at most `limit`
        # pages; `_MAX_PAGES` is the floor that covers the unbounded reads.
        budget = _MAX_PAGES if limit is None else max(_MAX_PAGES, limit)

        items: list[dict] = []
        for _ in range(budget):
            if limit is not None:
                kwargs["Limit"] = limit - len(items)
            response = self.query(**kwargs)
            items.extend(response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if start_key is None:
                return items
            if limit is not None and len(items) >= limit:
                return items[:limit]
            kwargs["ExclusiveStartKey"] = start_key

        raise ResultSetTooLarge(f"read did not complete within {budget} pages ({len(items)} items)")


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
