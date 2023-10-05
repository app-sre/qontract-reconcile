import logging
import sys

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient

QONTRACT_INTEGRATION = "openshift-serviceaccount-tokens"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_sa_token_oc_resource(name, sa_token):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name,
        },
        "data": {"token": sa_token},
    }
    return OR(
        body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
    )


def get_tokens_for_service_account(
    service_account: str, tokens: list[dict]
) -> list[dict]:
    result = []
    for token in tokens:
        # if we start creating a dedicated token secret for this integration,
        # it could have a label or annotation we could rely on.
        if (
            token["metadata"]
            .get("annotations", {})
            .get("kubernetes.io/service-account.name")
            == service_account
            and token["type"] == "kubernetes.io/service-account-token"
        ):
            result.append(token)
    return result


def fetch_desired_state(namespaces: list[dict], ri: ResourceInventory, oc_map: OC_Map):
    for namespace_info in namespaces:
        if not namespace_info.get("openshiftServiceAccountTokens"):
            continue
        namespace_name = namespace_info["name"]
        cluster_name = namespace_info["cluster"]["name"]
        oc = oc_map.get(cluster_name)
        if not oc:
            logging.log(level=oc.log_level, msg=oc.message)
            continue
        for sat in namespace_info["openshiftServiceAccountTokens"]:
            sa_name = sat["serviceAccountName"]
            sa_namespace_info = sat["namespace"]
            sa_namespace_name = sa_namespace_info["name"]
            sa_cluster_name = sa_namespace_info["cluster"]["name"]
            oc = oc_map.get(sa_cluster_name)
            if not oc:
                if oc.log_level >= logging.ERROR:
                    ri.register_error()
                logging.log(level=oc.log_level, msg=oc.message)
                continue

            all_tokens = oc.get_items(kind="Secret", namespace=sa_namespace_name)
            oc_resource_name = (
                sat.get("name") or f"{sa_cluster_name}-{sa_namespace_name}-{sa_name}"
            )
            try:
                sa_token_list = get_tokens_for_service_account(sa_name, all_tokens)
                sa_token_list.sort(key=lambda t: t["metadata"]["name"])
                sa_token = sa_token_list[0]["data"]["token"]
                cur = ri.get_current(
                    cluster_name, namespace_name, "Secret", oc_resource_name
                )
                if cur:
                    for token in sa_token_list:
                        if token["data"]["token"] == cur.body.get("data", {}).get(
                            "token"
                        ):
                            sa_token = token["data"]["token"]
            except KeyError:
                logging.log(
                    level=logging.ERROR,
                    msg=f"[{sa_cluster_name}/{sa_namespace_name}] Token not found for service account: {sa_name}",
                )
                raise
            except IndexError:
                logging.log(
                    level=logging.ERROR,
                    msg=f"[{sa_cluster_name}/{sa_namespace_name}] 0 Secret found for service account: {sa_name}",
                )
                raise

            oc_resource = construct_sa_token_oc_resource(oc_resource_name, sa_token)
            ri.add_desired(
                cluster_name, namespace_name, "Secret", oc_resource_name, oc_resource
            )


def write_outputs_to_vault(vault_path, ri):
    integration_name = QONTRACT_INTEGRATION.replace("_", "-")
    vault_client = VaultClient()
    for cluster, namespace, _, data in ri:
        for name, d_item in data["desired"].items():
            body_data = d_item.body["data"]
            # write secret to per-namespace location
            secret_path = (
                f"{vault_path}/{integration_name}/" + f"{cluster}/{namespace}/{name}"
            )
            secret = {"path": secret_path, "data": body_data}
            vault_client.write(secret)
            # write secret to shared-resources location
            secret_path = (
                f"{vault_path}/{integration_name}/" + f"shared-resources/{name}"
            )
            secret = {"path": secret_path, "data": body_data}
            vault_client.write(secret)


def canonicalize_namespaces(namespaces):
    canonicalized_namespaces = []
    for namespace_info in namespaces:
        if ob.is_namespace_deleted(namespace_info):
            continue
        ob.aggregate_shared_resources(namespace_info, "openshiftServiceAccountTokens")
        openshift_serviceaccount_tokens = namespace_info.get(
            "openshiftServiceAccountTokens"
        )
        if openshift_serviceaccount_tokens:
            canonicalized_namespaces.append(namespace_info)
            for sat in openshift_serviceaccount_tokens:
                canonicalized_namespaces.append(sat["namespace"])

    return canonicalized_namespaces


@defer
def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    vault_output_path="",
    defer=None,
):
    namespaces = canonicalize_namespaces(queries.get_serviceaccount_tokens())
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Secret"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)
    if not dry_run and vault_output_path:
        write_outputs_to_vault(vault_output_path, ri)

    if ri.has_error_registered():
        sys.exit(1)
