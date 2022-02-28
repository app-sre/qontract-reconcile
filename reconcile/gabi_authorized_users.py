import logging
import sys
from datetime import datetime, date
from typing import Iterable, Mapping, Optional
from reconcile.status import ExitCodes

from reconcile.utils.aggregated_list import RunnerException
from reconcile import queries
import reconcile.openshift_base as ob
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.defer import defer

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


def fetch_desired_state(
    gabi_instances: Iterable[Mapping], ri: ResourceInventory
) -> None:
    for g in gabi_instances:
        exp_date = datetime.strptime(g["expirationDate"], "%Y-%m-%d").date()
        users = [u["github_username"] for u in g["users"]]
        if exp_date < date.today():
            users = []
        elif (exp_date - date.today()).days > EXPIRATION_MAX:
            raise RunnerException(
                f'The maximum expiration date of {g["name"]} '
                f"shall not exceed {EXPIRATION_MAX} days form today"
            )
        resource = construct_gabi_oc_resource(g["name"], users)
        for i in g["instances"]:
            namespace = i["namespace"]
            account = i["account"]
            identifier = i["identifier"]
            tf_resources = namespace["terraformResources"]
            found = False
            for t in tf_resources:
                if t["provider"] != "rds":
                    continue
                if (t["account"], t["identifier"]) == (account, identifier):
                    found = True
                    break
            if not found:
                raise RunnerException(
                    f"Could not find rds identifier {identifier} "
                    f'for account {account} in namespace {namespace["name"]}'
                )
            cluster = namespace["cluster"]["name"]
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
