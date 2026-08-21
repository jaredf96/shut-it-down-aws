"""Orchestrates the individual scanners.

This is the single place the API talks to. Keeping the orchestration here
(instead of in main.py) makes it easy to later add caching, persistence to
DynamoDB, or background jobs without touching the route handlers.
"""

from __future__ import annotations

import logging
import time

import boto3

from app.models import Resource
from app.pricing import pricing_service
from app.scanners import SCANNERS
from app.utils import get_regions

logger = logging.getLogger("app.scan")


def scan_one(
    scanner_key: str,
    regions: list[str] | None = None,
    session=None,
    failed_regions: dict[str, str] | None = None,
) -> list[Resource]:
    """Run a single scanner by its key (e.g. "ec2"). Raises KeyError if unknown.

    `session` is an optional boto3 Session, used to scan a specific
    (assumed-role) account; None uses the default credential chain. Pass
    `failed_regions` to collect the regions the sweep could not read. Returned
    resources are stamped with cost estimates.
    """
    scanner = SCANNERS[scanner_key]
    return pricing_service.annotate(
        scanner.scan(regions, session=session, failed_regions=failed_regions)
    )


def region_failures(failed: dict[str, str]) -> list[dict[str, object]]:
    """Render collected region failures as the API's `regions_failed` entries.

    `account_id`/`account_label` mirror `Resource`: None in single-account mode,
    stamped by `multi_account_service` when a tenant has registered accounts.
    """
    return [
        {"region": region, "reason": reason, "account_id": None, "account_label": None}
        for region, reason in sorted(failed.items())
    ]


def scan_all(regions: list[str] | None = None, session=None) -> dict[str, object]:
    """Run every scanner and return a combined, summarized result.

    Regions are discovered once here and passed down to every scanner, so a
    single aggregate scan makes one `describe_regions` call instead of one per
    scanner. Each scanner then fans its region sweep out concurrently.
    """
    session = session or boto3.Session()
    regions = regions or get_regions(session)

    all_resources: list[Resource] = []
    # Shared across scanners: a disabled or unpermitted region fails for all of
    # them, and the caller wants "regions I could not read", not one list per
    # scanner.
    failed_regions: dict[str, str] = {}
    logger.info("scan start: %d region(s) across %d scanners", len(regions), len(SCANNERS))
    started = time.perf_counter()

    for key in SCANNERS:
        t0 = time.perf_counter()
        try:
            found = scan_one(key, regions, session=session, failed_regions=failed_regions)
        except Exception:
            # One failing scanner should never break the whole scan.
            logger.exception("scanner %s failed", key)
            found = []
        all_resources.extend(found)
        logger.info("  %-14s %3d resource(s) in %6.2fs", key, len(found), time.perf_counter() - t0)

    if failed_regions:
        logger.warning(
            "scan could not read %d of %d region(s): %s",
            len(failed_regions),
            len(regions),
            ", ".join(f"{r} ({reason})" for r, reason in sorted(failed_regions.items())),
        )

    logger.info(
        "scan done: %d resource(s) in %.2fs", len(all_resources), time.perf_counter() - started
    )
    return {
        "summary": summarize(all_resources),
        "resources": all_resources,
        "regions_failed": region_failures(failed_regions),
    }


def summarize(resources: list[Resource]) -> dict[str, object]:
    """Small rollup the frontend can show at the top of the dashboard."""
    by_risk: dict[str, int] = {}
    cost_total = 0.0
    for r in resources:
        by_risk[r.risk_level.value] = by_risk.get(r.risk_level.value, 0) + 1
        if r.estimated_monthly_cost:
            cost_total += r.estimated_monthly_cost

    return {
        "total_resources": len(resources),
        "by_risk_level": by_risk,
        "estimated_monthly_cost": round(cost_total, 2),
    }
