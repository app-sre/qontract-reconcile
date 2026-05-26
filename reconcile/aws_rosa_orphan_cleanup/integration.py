from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError
from prometheus_client.core import Gauge
from pydantic import BaseModel
from requests import HTTPError

from reconcile.gql_definitions.aws_rosa_orphan_cleanup.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.datetime_util import utc_now
from reconcile.utils.defer import defer
from reconcile.utils.metrics import pushgateway_registry
from reconcile.utils.ocm_base_client import OCMBaseClient, init_ocm_base_client
from reconcile.utils.secret_reader import create_secret_reader

if TYPE_CHECKING:
    from collections.abc import Callable

    from mypy_boto3_ec2 import EC2Client

QONTRACT_INTEGRATION = "aws-rosa-orphan-cleanup"

# EC2 instance pricing (hourly) - approximate costs in USD
EC2_HOURLY_COST = {
    "t3.xlarge": 0.1664,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "m6i.xlarge": 0.192,
    "m6i.2xlarge": 0.384,
    "m6i.4xlarge": 0.768,
    "default": 0.20,
}

# Prometheus metrics for pushgateway
orphaned_instances_count = Gauge(
    name="rosa_orphaned_ec2_instances_count",
    documentation="Number of orphaned ROSA EC2 instances detected",
    labelnames=["account", "region"],
    registry=pushgateway_registry,
)

orphaned_instances_cost = Gauge(
    name="rosa_orphaned_ec2_instances_estimated_cost_hourly",
    documentation="Estimated hourly cost of orphaned ROSA EC2 instances in USD",
    labelnames=["account", "region"],
    registry=pushgateway_registry,
)

cleanup_job_success = Gauge(
    name="rosa_orphan_cleanup_job_success",
    documentation="1 if cleanup job succeeded, 0 if failed",
    labelnames=["account"],
    registry=pushgateway_registry,
)


class OrphanedInstance(BaseModel, frozen=True):
    instance_id: str
    instance_type: str
    launch_time: datetime
    cluster_name: str
    cluster_id: str | None
    tags: dict[str, str]


def get_ec2_hourly_cost(instance_type: str) -> float:
    """Get hourly cost for EC2 instance type."""
    return EC2_HOURLY_COST.get(instance_type, EC2_HOURLY_COST["default"])


def get_rosa_ec2_instances(ec2_client: EC2Client) -> list[OrphanedInstance]:
    """Get all running EC2 instances with ROSA tags."""
    instances = []

    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "tag-key", "Values": ["api.openshift.com/name"]},
        ]
    ):
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}

                cluster_name = tags.get("api.openshift.com/name", "")
                cluster_id = tags.get("api.openshift.com/id")

                if not cluster_name:
                    continue

                instances.append(
                    OrphanedInstance(
                        instance_id=instance["InstanceId"],
                        instance_type=instance["InstanceType"],
                        launch_time=instance["LaunchTime"],
                        cluster_name=cluster_name,
                        cluster_id=cluster_id,
                        tags=tags,
                    )
                )

    return instances


def check_cluster_exists_in_ocm(
    ocm_client: OCMBaseClient, cluster_id: str | None, cluster_name: str
) -> bool:
    """Check if cluster still exists in OCM."""
    if not cluster_id:
        logging.warning(
            f"Cluster {cluster_name} has no cluster ID tag, cannot verify in OCM"
        )
        return True

    try:
        ocm_client.get(f"/api/clusters_mgmt/v1/clusters/{cluster_id}")
        return True
    except HTTPError as e:
        if e.response.status_code == 404:
            return False
        logging.warning(
            f"Error checking cluster {cluster_name} ({cluster_id}) in OCM: {e}"
        )
        return True


def terminate_orphaned_instance(
    ec2_client: EC2Client,
    instance: OrphanedInstance,
    dry_run: bool,
) -> None:
    """Terminate an orphaned EC2 instance."""
    logging.info(
        f"Terminating orphaned instance {instance.instance_id} "
        f"from cluster {instance.cluster_name} "
        f"(type: {instance.instance_type}, launched: {instance.launch_time})"
    )

    try:
        ec2_client.terminate_instances(
            InstanceIds=[instance.instance_id], DryRun=dry_run
        )
        if not dry_run:
            logging.info(f"Successfully terminated instance {instance.instance_id}")
    except ClientError as e:
        if "DryRunOperation" in str(e):
            logging.info(f"DRY RUN: Would terminate instance {instance.instance_id}")
        else:
            raise


def init_ocm_client_for_account(
    account: Any,
    ocm_clients: dict[str, OCMBaseClient],
    secret_reader: Any,
    defer_func: Callable | None,
) -> OCMBaseClient | None:
    """Initialize OCM client for account if needed. Returns first available OCM client."""
    if not (rosa_config := account.rosa):
        return None

    for ocm_env in rosa_config.ocm_environments or []:
        ocm_env_name = ocm_env.ocm.name
        if ocm_env_name not in ocm_clients:
            try:
                ocm_clients[ocm_env_name] = init_ocm_base_client(
                    ocm_env.ocm.environment, secret_reader
                )
                if defer_func:
                    defer_func(ocm_clients[ocm_env_name].close)
            except Exception as e:
                logging.error(
                    f"Failed to initialize OCM client for {ocm_env_name}: {e}"
                )
                cleanup_job_success.labels(account=account.name).set(0)
                continue

        return ocm_clients[ocm_env_name]

    return None


def scan_region_for_orphans(
    account_name: str,
    region: str,
    ec2_client: EC2Client,
    ocm_client: OCMBaseClient | None,
    orphan_age_threshold: datetime,
) -> list[OrphanedInstance]:
    """Scan a single region for orphaned ROSA instances."""
    instances = get_rosa_ec2_instances(ec2_client)

    if not instances:
        logging.debug(f"No ROSA instances found in {account_name}/{region}")
        return []

    logging.info(f"Found {len(instances)} ROSA instances in {account_name}/{region}")

    if not ocm_client:
        logging.warning(
            f"No OCM client available for account {account_name}, "
            "skipping cluster validation"
        )
        return []

    orphans = []
    for instance in instances:
        if instance.launch_time > orphan_age_threshold:
            logging.debug(
                f"Instance {instance.instance_id} is too recent "
                f"(launched {instance.launch_time}), skipping"
            )
            continue

        cluster_exists = check_cluster_exists_in_ocm(
            ocm_client, instance.cluster_id, instance.cluster_name
        )

        if not cluster_exists:
            logging.warning(
                f"Orphaned instance detected: {instance.instance_id} "
                f"from deleted cluster {instance.cluster_name}"
            )
            orphans.append(instance)

    return orphans


def cleanup_orphaned_instances(
    account_name: str,
    region: str,
    orphans: list[OrphanedInstance],
    dry_run: bool,
    aws_api: AWSApi,
) -> None:
    """Process orphaned instances: emit metrics and optionally terminate them."""
    if not orphans:
        return

    count = len(orphans)
    total_cost = sum(
        get_ec2_hourly_cost(instance.instance_type) for instance in orphans
    )

    orphaned_instances_count.labels(account=account_name, region=region).set(count)
    orphaned_instances_cost.labels(account=account_name, region=region).set(total_cost)

    logging.warning(
        f"Found {count} orphaned instances in {account_name}/{region} "
        f"with estimated cost ${total_cost:.2f}/hour"
    )

    if not dry_run:
        session = aws_api.get_session(account_name)
        ec2_client = aws_api.get_session_client(session, "ec2", region)

        for instance in orphans:
            try:
                terminate_orphaned_instance(ec2_client, instance, dry_run)
            except Exception as e:
                logging.error(
                    f"Failed to terminate instance {instance.instance_id}: {e}"
                )
                cleanup_job_success.labels(account=account_name).set(0)


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 1,
    orphan_age_hours: int = 24,
    defer: Callable | None = None,
) -> None:
    """Main integration entry point."""
    now = utc_now()
    orphan_age_threshold = now - timedelta(hours=orphan_age_hours)

    gqlapi = gql.get_api()
    aws_accounts = aws_accounts_query(gqlapi.query).accounts

    if not aws_accounts:
        logging.warning("No AWS accounts found")
        return

    accounts_dicted = [
        account.model_dump(by_alias=True) for account in aws_accounts or []
    ]
    secret_reader = create_secret_reader(
        use_vault=get_app_interface_vault_settings().vault
    )
    aws_api = AWSApi(1, accounts_dicted, secret_reader=secret_reader, init_users=False)
    if defer:
        defer(aws_api.cleanup)

    ocm_clients: dict[str, OCMBaseClient] = {}
    total_orphans_by_account: dict[str, dict[str, list[OrphanedInstance]]] = (
        defaultdict(lambda: defaultdict(list))
    )

    for account in aws_accounts or []:
        account_name = account.name

        ocm_client = init_ocm_client_for_account(
            account, ocm_clients, secret_reader, defer
        )

        regions = account.supported_deployment_regions or [
            account.resources_default_region
        ]
        logging.info(f"Scanning account {account_name} in regions: {regions}")

        for region in regions:
            try:
                session = aws_api.get_session(account_name)
                ec2_client = aws_api.get_session_client(session, "ec2", region)

                orphans = scan_region_for_orphans(
                    account_name, region, ec2_client, ocm_client, orphan_age_threshold
                )

                total_orphans_by_account[account_name][region].extend(orphans)
                cleanup_job_success.labels(account=account_name).set(1)

            except Exception:
                logging.exception(f"Error scanning {account_name}/{region}")
                cleanup_job_success.labels(account=account_name).set(0)

    for account_name, regions_data in total_orphans_by_account.items():
        for region, orphans in regions_data.items():
            cleanup_orphaned_instances(account_name, region, orphans, dry_run, aws_api)

    logging.info("ROSA orphan cleanup completed")
