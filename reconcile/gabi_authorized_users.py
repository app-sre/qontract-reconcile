import logging
import sys
from collections.abc import (
    Iterable,
    Mapping,
)
from datetime import (
    date,
    datetime,
)
from typing import (
    Any,
    Optional,
)

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.aggregated_list import RunnerException
from reconcile.utils.defer import defer
from reconcile.utils.external_resources import get_external_resource_specs
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    ResourceInventory,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "gabi-authorized-users"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
EXPIRATION_MAX = 90


def construct_gabi_oc_resource(name: str, users: Iterable[str]) -> OpenshiftResource:
    body = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "annotations": {"qontract.recycle": "true"}},
        "data": {"authorized-users.yaml": "\n".join(users)},
    }
    return OpenshiftResource(
        body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
    )


def get_usernames(
    users: Iterable[Mapping[str, Any]], cluster: Mapping[str, Any]
) -> list[str]:
    """Extract usernames from objects based on used cluster authentication methods."""
    user_keys = ob.determine_user_keys_for_access(cluster["name"], cluster["auth"])
    return [u[key] for u in users for key in user_keys]


def fetch_desired_state(
    gabi_instances: Iterable[Mapping], ri: ResourceInventory
) -> None:
    for g in gabi_instances:
        exp_date = datetime.strptime(g["expirationDate"], "%Y-%m-%d").date()
        if (exp_date - date.today()).days > EXPIRATION_MAX:
            raise RunnerException(
                f'The maximum expiration date of {g["name"]} '
                f"shall not exceed {EXPIRATION_MAX} days form today"
            )
        for i in g["instances"]:
            namespace = i["namespace"]
            account = i["account"]
            identifier = i["identifier"]
            specs = get_external_resource_specs(namespace)
            found = False
            for spec in specs:
                if spec.provider != "rds":
                    continue
                if (spec.provisioner_name, spec.identifier) == (account, identifier):
                    found = True
                    break
            if not found:
                raise RunnerException(
                    f"Could not find rds identifier {identifier} "
                    f'for account {account} in namespace {namespace["name"]}'
                )
            cluster = namespace["cluster"]["name"]
            users = (
                get_usernames(g["users"], namespace["cluster"])
                if exp_date >= date.today()
                else []
            )
            resource = construct_gabi_oc_resource(g["name"], users)
            ri.add_desired(cluster, namespace["name"], "ConfigMap", g["name"], resource)


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host=True,
    defer=None,
):
    gabi_instances = queries.get_gabi_instances()
    if not gabi_instances:
        logging.debug("No gabi instances found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    gabi_namespaces = [i["namespace"] for g in gabi_instances for i in g["instances"]]

    ri, oc_map = ob.fetch_current_state(
        namespaces=gabi_namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["ConfigMap"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    fetch_desired_state(gabi_instances, ri)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
