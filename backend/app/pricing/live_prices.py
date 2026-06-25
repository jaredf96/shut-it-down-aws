"""Live AWS Pricing API lookups (opt-in).

Scoped on purpose: only the dimensions we can query cleanly are wired up
(NAT Gateway hourly, EBS per-GB-month). Everything else falls back to the static
baseline. This is how the static estimator gets replaced gradually — add a
method here and the service prefers it automatically.

Every lookup is cached in-process and defensive: any error (missing permission,
unknown region, parse failure) returns None so the caller falls back to static.
"""

from __future__ import annotations

import json

import boto3

from app.pricing.static_prices import HOURS_PER_MONTH

# Pricing API "location" names for the regions we support.
_REGION_TO_LOCATION = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-south-1": "Asia Pacific (Mumbai)",
}


def _first_usd_price(price_list: list) -> float | None:
    """Pull the first on-demand USD unit price out of a GetProducts response."""
    for product_json in price_list:
        data = json.loads(product_json)
        on_demand = data.get("terms", {}).get("OnDemand", {})
        for term in on_demand.values():
            for dimension in term.get("priceDimensions", {}).values():
                usd = dimension.get("pricePerUnit", {}).get("USD")
                if usd is not None:
                    return float(usd)
    return None


class LivePricer:
    """Thin, cached wrapper over the AWS Pricing API."""

    def __init__(self, client=None):
        # The Pricing API is only served from a few regions; us-east-1 is safest.
        self._client = client or boto3.client("pricing", region_name="us-east-1")
        self._cache: dict[tuple, float | None] = {}

    def _get_products(self, service_code: str, filters: list[dict]) -> float | None:
        try:
            response = self._client.get_products(
                ServiceCode=service_code, Filters=filters, MaxResults=1
            )
            return _first_usd_price(response.get("PriceList", []))
        except Exception:
            # Pricing is best-effort: never let a lookup failure break a scan.
            return None

    def nat_gateway_monthly(self, region: str) -> float | None:
        location = _REGION_TO_LOCATION.get(region)
        if not location:
            return None
        key = ("nat", region)
        if key not in self._cache:
            hourly = self._get_products(
                "AmazonVPC",
                [
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "NAT Gateway"},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                    {
                        "Type": "TERM_MATCH",
                        "Field": "groupDescription",
                        "Value": "Hourly charge for NAT Gateways",
                    },
                ],
            )
            self._cache[key] = round(hourly * HOURS_PER_MONTH, 2) if hourly is not None else None
        return self._cache[key]

    def ebs_gb_month(self, region: str, volume_type: str | None) -> float | None:
        location = _REGION_TO_LOCATION.get(region)
        if not location or not volume_type:
            return None
        key = ("ebs", region, volume_type)
        if key not in self._cache:
            self._cache[key] = self._get_products(
                "AmazonEC2",
                [
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                    {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": volume_type},
                ],
            )
        return self._cache[key]
