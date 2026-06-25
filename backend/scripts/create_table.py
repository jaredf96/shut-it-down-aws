"""Create the DynamoDB table used for scan history.

Run as a module from the `backend/` directory so the `app` package is importable.

Against real AWS:
    DYNAMODB_TABLE_NAME=cloud-lab-scans python -m scripts.create_table

Against local DynamoDB (e.g. dynamodb-local on port 8001):
    DYNAMODB_TABLE_NAME=cloud-lab-scans \
    DYNAMODB_ENDPOINT_URL=http://localhost:8001 \
    python -m scripts.create_table
"""

from __future__ import annotations

import sys

from app import config
from app.repositories import scan_repository


def main() -> int:
    table = config.get_table_name()
    if not table:
        print("Set DYNAMODB_TABLE_NAME before running this script.", file=sys.stderr)
        return 1

    scan_repository.ensure_table()
    endpoint = config.get_dynamodb_endpoint_url() or "(default AWS endpoint)"
    print(f"Table '{table}' is ready at {endpoint}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
