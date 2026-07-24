"""Run a per-region scanner body across many regions concurrently.

Scanners are I/O-bound: each region is a blocking boto3 ``Describe`` call, and
a real account has ~17 enabled regions. Sweeping them serially dominates scan
time even for an empty account. A thread pool collapses the sweep to roughly the
latency of the slowest single region.

Kept in one place so boto3's thread-safety rules are handled once:
- botocore's client *factory* on a shared ``Session`` is not guaranteed safe to
  call concurrently, so ``make_client`` serializes just the (cheap, local)
  construction with a lock; the actual network calls run fully in parallel.
- Credentials are resolved once up front so worker threads don't race on the
  credential-provider chain (an SSO token refresh firing on N threads at once).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.models import Resource

_CLIENT_LOCK = threading.Lock()

# Cap fan-out so a many-region account does not open dozens of sockets at once.
_MAX_WORKERS = 16


def make_client(session: boto3.Session, service: str, region: str):
    """Construct a boto3 client for one service/region, thread-safely."""
    with _CLIENT_LOCK:
        return session.client(service, region_name=region)


def scan_regions(
    scan_region: Callable[[str], list[Resource]],
    regions: list[str],
    session: boto3.Session,
    *,
    max_workers: int = _MAX_WORKERS,
) -> list[Resource]:
    """Call ``scan_region(region)`` for every region and flatten the results.

    A region that errors (disabled, or lacking permission) is skipped, matching
    the previous per-region try/except behavior. Output preserves ``regions``
    order regardless of which threads finish first, so scans stay deterministic.
    """
    if not regions:
        return []

    # Single region (notably every test, pinned to one region): stay on the
    # calling thread — no pool, no thread-safety concerns, identical behavior.
    if len(regions) == 1:
        try:
            return list(scan_region(regions[0]))
        except (BotoCoreError, ClientError):
            return []

    # Freeze credentials once before fanning out.
    try:
        session.get_credentials()
    except (BotoCoreError, ClientError):
        pass

    by_region: dict[str, list[Resource]] = {}
    workers = min(max_workers, len(regions))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan") as pool:
        futures = {pool.submit(scan_region, region): region for region in regions}
        for future in as_completed(futures):
            region = futures[future]
            try:
                by_region[region] = future.result()
            except (BotoCoreError, ClientError):
                by_region[region] = []  # region disabled or not permitted

    resources: list[Resource] = []
    for region in regions:
        resources.extend(by_region.get(region, []))
    return resources
