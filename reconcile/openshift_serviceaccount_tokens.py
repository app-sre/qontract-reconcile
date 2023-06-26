import logging
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import (
    Optional,
    Union,
    cast,
)

import reconcile.openshift_base as ob
from reconcile.gql_definitions.openshift_service_account_tokens.openshift_service_account_token_fragment import (
    NamespaceV1 as SANamespace,
)
from reconcile.gql_definitions.openshift_service_account_tokens.openshift_service_account_tokens import (
    NamespaceV1,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.openshift_service_account_tokens import (
    get_openshift_service_account_tokens,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "openshift-serviceaccount-tokens"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class SANamespaceV2(SANamespace):
    """We need this to comply with OCMap protocol standards"""

    cluster_admin: Optional[bool] = None


def construct_sa_token_oc_resource(name: str, sa_token: Mapping) -> OR:
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


def fetch_desired_state(
    namespaces: Iterable[Union[NamespaceV1, SANamespaceV2]],
    ri: ResourceInventory,
    oc_map: OCMap,
) -> None:
    for namespace_info in namespaces:
        if isinstance(namespace_info, SANamespace):
            continue
        oc = oc_map.get(namespace_info.cluster.name)
        if isinstance(oc, OCLogMsg):
            logging.log(level=oc.log_level, msg=oc.message)
            continue
        for sat in namespace_info.openshift_service_account_tokens or []:
            sa_name = sat.service_account_name
            sa_namespace_info = sat.namespace
            sa_namespace_name = sa_namespace_info.name
            sa_cluster_name = sa_namespace_info.cluster.name
            oc = oc_map.get(sa_cluster_name)
            if isinstance(oc, OCLogMsg):
                if oc.log_level >= logging.ERROR:
                    ri.register_error()
                logging.log(level=oc.log_level, msg=oc.message)
                continue

            all_tokens = oc.get_items(kind="Secret", namespace=sa_namespace_name)
            oc_resource_name = (
                sat.name or f"{sa_cluster_name}-{sa_namespace_name}-{sa_name}"
            )
            try:
                sa_token_list = get_tokens_for_service_account(sa_name, all_tokens)
                sa_token_list.sort(key=lambda t: t["metadata"]["name"])
                sa_token = sa_token_list[0]["data"]["token"]
                cur = ri.get_current(
                    namespace_info.cluster.name,
                    namespace_info.name,
                    "Secret",
                    oc_resource_name,
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
                namespace_info.cluster.name,
                namespace_info.name,
                "Secret",
                oc_resource_name,
                oc_resource,
            )


def write_outputs_to_vault(vault_path: str, ri: ResourceInventory) -> None:
    integration_name = QONTRACT_INTEGRATION.replace("_", "-")
    # cast to make mypy happy
    vault_client = cast(_VaultClient, VaultClient())
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


def canonicalize_namespaces(
    namespaces: Iterable[NamespaceV1],
) -> list[Union[NamespaceV1, SANamespaceV2]]:
    canonicalized_namespaces: list[Union[NamespaceV1, SANamespaceV2]] = []
    for namespace_info in namespaces:
        if ob.is_namespace_marked_for_deletion(namespace_info):
            continue
        aggregated = ob.aggregate_shared_service_account_token_namespaces(
            namespace_info
        )
        namespace_info.openshift_service_account_tokens = aggregated
        if namespace_info.openshift_service_account_tokens:
            canonicalized_namespaces.append(namespace_info)
            for sat in namespace_info.openshift_service_account_tokens:
                canonicalized_namespaces.append(
                    SANamespaceV2(**sat.namespace.dict(by_alias=True))
                )

    return canonicalized_namespaces


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    vault_output_path: str = "",
    defer: Optional[Callable] = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    all_namespaces = get_openshift_service_account_tokens()
    namespaces = canonicalize_namespaces(all_namespaces)
    oc_map = init_oc_map_from_namespaces(
        namespaces=namespaces,
        secret_reader=secret_reader,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)
    ri = ob.get_resource_inventory(
        oc_map=oc_map,
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Secret"],
    )
    fetch_desired_state(namespaces, ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)
    if not dry_run and vault_output_path:
        write_outputs_to_vault(vault_output_path, ri)

    if ri.has_error_registered():
        raise RuntimeError("Error provisioning service account tokens")
