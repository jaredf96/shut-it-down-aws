"""Domain-level errors that the API layer maps to HTTP responses.

Keeping these here (rather than leaking botocore exceptions upward) means the
routes never have to know which storage backend raised, and an infrastructure
failure becomes a deliberate, structured response instead of an unhandled 500.
"""

from __future__ import annotations


class PersistenceUnavailable(RuntimeError):
    """The persistence layer could not be reached or authenticated.

    Raised for connectivity and credential problems — an expired SSO session, a
    stopped local DynamoDB container, a DNS or timeout failure. It deliberately
    does NOT cover errors where DynamoDB was reached and answered (those surface
    as botocore ``ClientError`` so callers can handle them meaningfully, e.g.
    ``ResourceInUseException`` during table creation).
    """
