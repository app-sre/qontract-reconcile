import logging
import re
import sys
from typing import Iterable, Mapping


from reconcile import queries

from reconcile.status import ExitCodes
from reconcile.utils import dnsutils
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.utils.terraform_client import TerraformClient as Terraform


QONTRACT_INTEGRATION = "terraform_aws_route53"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def build_desired_state(
    zones: Iterable[Mapping], all_accounts: Iterable[Mapping], settings: Mapping
) -> list[dict]:
    """
    Build the desired state from the app-interface resources

    :param zones: List of zone resources to build state for
    :type zones: list of dict
    :return: State
    :rtype: list of dict
    """

    desired_state = []
    for zone in zones:
        account = zone["account"]
        account_name = account["name"]

        zone_name = zone["name"]
        zone_values = {"name": zone_name, "account_name": account_name, "records": []}

        # a vpc will be referenced for a zone to be considered private
        vpc = zone.get("vpc")
        if vpc:
            zone_values["vpc"] = {"vpc_id": vpc["vpc_id"], "vpc_region": vpc["region"]}

        # Check if we have unmanaged_record_names (urn) and compile them
        # all as regular expressions
        urn_compiled = []
        for urn in zone.get("unmanaged_record_names", []):
            urn_compiled.append(re.compile(urn))

        for record in zone["records"]:
            record_name = record["name"]
            record_type = record["type"]

            # Check if this record should be ignored
            # as per 'unmanaged_record_names'
            ignored = False
            for regex in urn_compiled:
                if regex.fullmatch(record["name"]):
                    logging.debug(
                        f"{zone_name}: excluding unmanaged "
                        f"record {record_name} because it matched "
                        f"unmanaged_record_names pattern "
                        f"'{regex.pattern}'"
                    )
                    ignored = True
            if ignored:
                continue

            # We use the record object as-is from the list as the terraform
            # data to apply. This makes things simpler and map 1-to-1 with
            # Terraform's capabilities. As such we need to remove (pop) some of
            # the keys we use for our own features

            # Process '_target_cluster'
            target_cluster = record.pop("_target_cluster", None)
            if target_cluster:
                target_cluster_elb = target_cluster["elbFQDN"]

                if target_cluster_elb is None or target_cluster_elb == "":
                    msg = (
                        f"{zone_name}: field `_target_cluster` for record "
                        f"{record_name} of type {record_type} points to a "
                        f"cluster that has an empty elbFQDN field."
                    )
                    logging.error(msg)
                    sys.exit(ExitCodes.ERROR)

                record_values = []
                if record_type == "A":
                    record_values = dnsutils.get_a_records(target_cluster_elb)
                elif record_type == "CNAME":
                    record_values = [target_cluster_elb]
                else:
                    msg = (
                        f"{zone_name}: field `_target_cluster` found "
                        f"for record {record_name} of type {record_type}. "
                        f"The use of _target_cluster on this record type "
                        f"is not supported by the integration."
                    )
                    logging.error(msg)
                    sys.exit(ExitCodes.ERROR)

                if not record_values:
                    msg = (
                        f"{zone_name}: field `_target_cluster` found "
                        f"for record {record_name} of type {record_type} "
                        f"has no values! (invalid elb FQDN?)"
                    )
                    logging.error(msg)
                    sys.exit(ExitCodes.ERROR)

                msg = (
                    f"{zone_name}: field `_target_cluster` found "
                    f"for record {record_name} of type {record_type}. "
                    f"Value will be set to {record_values}"
                )
                logging.debug(msg)
                record["records"] = record_values

            # Process '_target_namespace_zone'
            target_namespace_zone = record.pop("_target_namespace_zone", None)
            if target_namespace_zone:
                tf_resources = target_namespace_zone["namespace"]["terraformResources"]
                tf_zone_name = target_namespace_zone["name"]
                tf_zone_resources = [
                    tfr
                    for tfr in tf_resources
                    if tfr["provider"] == "route53-zone" and tfr["name"] == tf_zone_name
                ]
                if not tf_zone_resources:
                    logging.error(
                        f"{zone_name}: field `_target_namespace_zone` found "
                        f"for record {record_name}, but target zone not found: "
                        f"{tf_zone_name}"
                    )
                    sys.exit(ExitCodes.ERROR)
                tf_zone_resource = tf_zone_resources[0]
                tf_zone_account_name = tf_zone_resource["account"]
                zone_account = [
                    a for a in all_accounts if a["name"] == tf_zone_account_name
                ][0]
                awsapi = AWSApi(1, [zone_account], settings=settings, init_users=False)
                tf_zone_region = (
                    tf_zone_resource.get("region")
                    or zone_account["resourcesDefaultRegion"]
                )
                tf_zone_ns_records = awsapi.get_route53_zone_ns_records(
                    tf_zone_account_name, tf_zone_name, tf_zone_region
                )
                if not tf_zone_ns_records:
                    logging.warning(
                        f"{zone_name}: field `_target_namespace_zone` found "
                        f"for record {record_name}, but target zone not found (yet): "
                        f"{tf_zone_name}"
                    )
                    continue
                logging.debug(
                    f"{zone_name}: field `_target_namespace_zone` found "
                    f"for record {record_name}, Values are: "
                    f"{tf_zone_ns_records}"
                )
                record["records"] = tf_zone_ns_records

            # Process '_healthcheck'
            healthcheck = record.pop("_healthcheck", None)
            if healthcheck:
                logging.debug(
                    f"{zone_name}: field `_healthcheck` found "
                    f"for record {record_name}. Values are: "
                    f"{healthcheck}"
                )
                record["healthcheck"] = healthcheck

            zone_values["records"].append(record)

        desired_state.append(zone_values)
    return desired_state


@defer
def run(
    dry_run=False,
    print_to_file=None,
    enable_deletion=True,
    thread_pool_size=10,
    defer=None,
):
    settings = queries.get_app_interface_settings()
    zones = queries.get_dns_zones()

    all_accounts = queries.get_aws_accounts()
    participating_account_names = [z["account"]["name"] for z in zones]
    participating_accounts = [
        a for a in all_accounts if a["name"] in participating_account_names
    ]

    ts = Terrascript(
        QONTRACT_INTEGRATION,
        "",
        thread_pool_size,
        participating_accounts,
        settings=settings,
    )

    desired_state = build_desired_state(zones, all_accounts, settings)

    ts.populate_route53(desired_state)
    working_dirs = ts.dump(print_to_file=print_to_file)
    aws_api = AWSApi(1, participating_accounts, settings=settings, init_users=False)

    if print_to_file:
        sys.exit(ExitCodes.SUCCESS)

    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        "",
        participating_accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )

    if tf is None:
        sys.exit(ExitCodes.ERROR)

    defer(tf.cleanup)

    _, err = tf.plan(enable_deletion)
    if err:
        sys.exit(ExitCodes.ERROR)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(ExitCodes.ERROR)
