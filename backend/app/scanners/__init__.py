"""Read-only AWS resource scanners.

Each scanner module exposes a `scan(regions=None) -> List[Resource]` function.
The registry below lets the scan service iterate over them uniformly.
"""

from . import (
    ebs_scanner,
    ec2_scanner,
    elastic_ip_scanner,
    load_balancer_scanner,
    nat_gateway_scanner,
    rds_scanner,
    s3_scanner,
)

# Maps the API path slug -> scanner module.
SCANNERS = {
    "ec2": ec2_scanner,
    "ebs": ebs_scanner,
    "elastic-ips": elastic_ip_scanner,
    "nat-gateways": nat_gateway_scanner,
    "load-balancers": load_balancer_scanner,
    "rds": rds_scanner,
    "s3": s3_scanner,
}

__all__ = [
    "SCANNERS",
    "ec2_scanner",
    "ebs_scanner",
    "elastic_ip_scanner",
    "nat_gateway_scanner",
    "load_balancer_scanner",
    "rds_scanner",
    "s3_scanner",
]
