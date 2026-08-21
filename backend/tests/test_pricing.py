import json

from app.pricing import pricing_service
from app.pricing.live_prices import LivePricer
from app.services import scan_all


def _res(rtype, status="running", details=None, region="us-east-1"):
    return {
        "resource_type": rtype,
        "resource_id": "x",
        "region": region,
        "status": status,
        "details": details or {},
    }


# --- static estimates ----------------------------------------------------


def test_static_nat_gateway_estimate():
    est = pricing_service.estimate(_res("NAT Gateway"))
    assert est["cost_source"] == "static"
    assert est["estimated_monthly_cost"] == round(0.045 * 730, 2)


def test_static_ebs_uses_size_and_type():
    res = _res("EBS Volume", details={"size_gb": 100, "volume_type": "gp3"})
    est = pricing_service.estimate(res)
    assert est["estimated_monthly_cost"] == 8.0  # 100 GB * $0.08
    assert est["cost_source"] == "static"


def test_running_vs_stopped_ec2():
    running = pricing_service.estimate(_res("EC2 Instance", details={"instance_type": "t3.micro"}))
    stopped = pricing_service.estimate(
        _res("EC2 Instance", status="stopped", details={"instance_type": "t3.micro"})
    )
    assert running["estimated_monthly_cost"] == round(0.0104 * 730, 2)
    assert stopped["estimated_monthly_cost"] == 0.0  # no compute charge when stopped


def test_all_eips_cost_the_public_ipv4_rate():
    # Since Feb 2024 AWS bills every public IPv4 address, associated or not.
    expected = round(0.005 * 730, 2)
    assert (
        pricing_service.estimate(_res("Elastic IP", status="unassociated"))[
            "estimated_monthly_cost"
        ]
        == expected
    )
    assert (
        pricing_service.estimate(_res("Elastic IP", status="associated"))["estimated_monthly_cost"]
        == expected
    )


def test_rds_prices_compute_and_allocated_storage():
    res = _res(
        "RDS Database",
        status="available",
        details={"instance_class": "db.t3.micro", "engine": "postgres", "allocated_storage_gb": 20},
    )
    est = pricing_service.estimate(res)
    # 0.017/hr * 730 + 20 GB * $0.115
    assert est["estimated_monthly_cost"] == round(round(0.017 * 730, 2) + 2.30, 2)
    assert est["cost_source"] == "static"


def test_rds_storage_is_billed_while_the_instance_is_stopped():
    # Unlike EC2, a stopped RDS instance keeps paying for provisioned storage —
    # the reason the scanner calls this out as HIGH risk in the first place.
    stopped = pricing_service.estimate(
        _res(
            "RDS Database",
            status="stopped",
            details={"instance_class": "db.t3.micro", "allocated_storage_gb": 20},
        )
    )
    assert stopped["estimated_monthly_cost"] == round(round(0.017 * 730, 2) + 2.30, 2)


def test_rds_falls_back_to_whichever_half_it_knows():
    # Either component alone is still a true floor, so report it rather than
    # dropping the resource to "unknown".
    unknown_class = pricing_service.estimate(
        _res(
            "RDS Database",
            details={"instance_class": "db.r5.24xlarge", "allocated_storage_gb": 100},
        )
    )
    assert unknown_class["estimated_monthly_cost"] == 11.50  # storage only

    no_storage = pricing_service.estimate(
        _res("RDS Database", details={"instance_class": "db.t3.micro"})
    )
    assert no_storage["estimated_monthly_cost"] == round(0.017 * 730, 2)

    neither = pricing_service.estimate(_res("RDS Database", details={"engine": "postgres"}))
    assert neither["estimated_monthly_cost"] is None
    assert neither["cost_source"] == "unknown"


def test_s3_and_unknown_type_are_unknown():
    assert pricing_service.estimate(_res("S3 Bucket", status="active"))["cost_source"] == "unknown"
    assert (
        pricing_service.estimate(_res("EC2 Instance", details={"instance_type": "weird.type"}))[
            "estimated_monthly_cost"
        ]
        is None
    )


# --- live overrides (mocked Pricing API) ---------------------------------


class _FakePricingClient:
    """Returns a canned NAT Gateway hourly price; everything else empty."""

    def __init__(self, hourly="0.052"):
        self.hourly = hourly

    def get_products(self, ServiceCode, Filters, MaxResults=1):  # noqa: N803 (boto3 casing)
        product = {
            "terms": {
                "OnDemand": {
                    "x": {"priceDimensions": {"y": {"pricePerUnit": {"USD": self.hourly}}}}
                }
            }
        }
        return {"PriceList": [json.dumps(product)]}


def test_live_overrides_static_for_nat():
    pricer = LivePricer(client=_FakePricingClient(hourly="0.052"))
    est = pricing_service.estimate(_res("NAT Gateway"), pricer=pricer)
    assert est["cost_source"] == "live"
    assert est["estimated_monthly_cost"] == round(0.052 * 730, 2)


def test_live_caches_lookups():
    client = _FakePricingClient()
    calls = {"n": 0}
    original = client.get_products

    def counting(**kwargs):
        calls["n"] += 1
        return original(**kwargs)

    client.get_products = counting
    pricer = LivePricer(client=client)
    pricer.nat_gateway_monthly("us-east-1")
    pricer.nat_gateway_monthly("us-east-1")
    assert calls["n"] == 1  # second call served from cache


def test_live_falls_back_to_static_on_error():
    class _Boom:
        def get_products(self, **kwargs):
            raise RuntimeError("no permission")

    pricer = LivePricer(client=_Boom())
    est = pricing_service.estimate(_res("NAT Gateway"), pricer=pricer)
    # Live failed -> static value, static source.
    assert est["cost_source"] == "static"
    assert est["estimated_monthly_cost"] == round(0.045 * 730, 2)


def test_unknown_region_skips_live():
    pricer = LivePricer(client=_FakePricingClient())
    assert pricer.nat_gateway_monthly("antarctica-1") is None


# --- integration: scan summary carries a fleet total ---------------------


def test_scan_summary_includes_cost_total(dynamo_table):
    import boto3

    from tests.conftest import REGION

    boto3.client("ec2", region_name=REGION).create_nat_gateway(
        SubnetId=_make_subnet(), AllocationId=_make_eip()
    )
    result = scan_all()
    assert "estimated_monthly_cost" in result["summary"]
    assert result["summary"]["estimated_monthly_cost"] >= round(0.045 * 730, 2)
    # Every resource is annotated.
    assert all(r.cost_source in ("static", "live", "unknown") for r in result["resources"])


def _make_subnet():
    import boto3

    from tests.conftest import REGION

    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    return ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]


def _make_eip():
    import boto3

    from tests.conftest import REGION

    return boto3.client("ec2", region_name=REGION).allocate_address(Domain="vpc")["AllocationId"]
