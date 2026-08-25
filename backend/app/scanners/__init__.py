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

# Maps the registry key -> scanner module.
SCANNERS = {
    "ec2": ec2_scanner,
    "ebs": ebs_scanner,
    "elastic-ips": elastic_ip_scanner,
    "nat-gateways": nat_gateway_scanner,
    "load-balancers": load_balancer_scanner,
    "rds": rds_scanner,
    "s3": s3_scanner,
}

# Display names for the registry keys. Used when a whole scanner is
# unavailable and the dashboard has to say *what* it could not see — "s3" is an
# internal key, not something to put in front of a reader.
SCANNER_LABELS = {
    "ec2": "EC2 instances",
    "ebs": "EBS volumes",
    "elastic-ips": "Elastic IPs",
    "nat-gateways": "NAT Gateways",
    "load-balancers": "Load Balancers",
    "rds": "RDS databases",
    "s3": "S3 buckets",
}

__all__ = [
    "SCANNER_LABELS",
    "SCANNERS",
    "ec2_scanner",
    "ebs_scanner",
    "elastic_ip_scanner",
    "nat_gateway_scanner",
    "load_balancer_scanner",
    "rds_scanner",
    "s3_scanner",
]
