import logging
import sys
from collections.abc import Callable, Iterable

import reconcile.openshift_base as ob
from reconcile.gql_definitions.openshift_serviceaccount_tokens.tokens import NamespaceV1
from reconcile.gql_definitions.openshift_serviceaccount_tokens.tokens import (
    query as serviceaccount_tokens_query,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient

QONTRACT_INTEGRATION = "openshift-serviceaccount-tokens"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_sa_token_oc_resource(name: str, sa_token: str) -> OR:
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
    namespaces: list[NamespaceV1], ri: ResourceInventory, oc_map: OC_Map
) -> None:
    for namespace in namespaces:
        if not namespace.openshift_service_account_tokens:
            continue

        if not (oc := oc_map.get(namespace.cluster.name)):
            logging.log(level=oc.log_level, msg=oc.message)
            continue

        for sat in namespace.openshift_service_account_tokens:
            oc = oc_map.get(sat.namespace.cluster.name)
            if not oc:
                if oc.log_level >= logging.ERROR:
                    ri.register_error()
                logging.log(level=oc.log_level, msg=oc.message)
                continue

            namespace_secrets = oc.get_items(
                kind="Secret", namespace=sat.namespace.name
            )
            try:
                sa_tokens = get_tokens_for_service_account(
                    sat.service_account_name, namespace_secrets
                )
                sa_tokens.sort(key=lambda t: t["metadata"]["name"])
                # take the first token found
                sa_token = sa_tokens[0]["data"]["token"]
            except KeyError:
                logging.error(
                    f"[{sat.namespace.cluster.name}/{sat.namespace.name}] Token not found for service account: {sat.service_account_name}"
                )
                raise
            except IndexError:
                logging.error(
                    f"[{sat.namespace.cluster.name}/{sat.namespace.name}] 0 Secret found for service account: {sat.service_account_name}"
                )
                raise

            oc_resource_name = (
                sat.name
                or f"{sat.namespace.cluster.name}-{sat.namespace.name}-{sat.service_account_name}"
            )
            oc_resource = construct_sa_token_oc_resource(oc_resource_name, sa_token)
            ri.add_desired(
                namespace.cluster.name,
                namespace.name,
                "Secret",
                oc_resource_name,
                oc_resource,
            )


def write_outputs_to_vault(
    vault_client: VaultClient, vault_path: str, ri: ResourceInventory
) -> None:
    integration_name = QONTRACT_INTEGRATION.replace("_", "-")
    for cluster, namespace, _, data in ri:
        for name, d_item in data["desired"].items():
            body_data = d_item.body["data"]
            # write secret to per-namespace location
            secret_path = (
                f"{vault_path}/{integration_name}/{cluster}/{namespace}/{name}"
            )
            secret = {"path": secret_path, "data": body_data}
            vault_client.write(secret)  # type: ignore
            # write secret to shared-resources location
            secret_path = f"{vault_path}/{integration_name}/shared-resources/{name}"
            secret = {"path": secret_path, "data": body_data}
            vault_client.write(secret)  # type: ignore


def canonicalize_namespaces(namespaces: Iterable[NamespaceV1]) -> list[NamespaceV1]:
    canonicalized_namespaces = []
    for namespace in namespaces:
        ob.aggregate_shared_resources_typed(namespace)
        if namespace.openshift_service_account_tokens:
            canonicalized_namespaces.append(namespace)
            for sat in namespace.openshift_service_account_tokens:
                if f"{sat.namespace.cluster.name}/{sat.namespace.name}" in [
                    f"{ns.cluster.name}/{ns.name}" for ns in canonicalized_namespaces
                ]:
                    # do not add duplicate namespaces to speed up fetch_current_state
                    continue
                canonicalized_namespaces.append(
                    # convert openshiftServiceAccountTokens.namespace to NamespaceV1
                    NamespaceV1(
                        **sat.namespace.dict(by_alias=True),
                        sharedResources=None,
                        openshiftServiceAccountTokens=None,
                    )
                )

    return canonicalized_namespaces


def get_namespaces_with_serviceaccount_tokens(
    query_func: Callable,
) -> list[NamespaceV1]:
    return [
        namespace
        for namespace in serviceaccount_tokens_query(query_func=query_func).namespaces
        or []
        if integration_is_enabled(QONTRACT_INTEGRATION, namespace.cluster)
        and not bool(namespace.delete)
        and (
            namespace.openshift_service_account_tokens
            or any(
                sr.openshift_service_account_tokens
                for sr in namespace.shared_resources or []
            )
        )
    ]


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    vault_output_path: str = "",
    defer: Callable | None = None,
) -> None:
    gql_api = gql.get_api()
    namespaces = canonicalize_namespaces(
        get_namespaces_with_serviceaccount_tokens(gql_api.query)
    )
    ri, oc_map = ob.fetch_current_state(
        namespaces=[ns.dict(by_alias=True) for ns in namespaces],
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Secret"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)
    if not dry_run and vault_output_path:
        write_outputs_to_vault(VaultClient(), vault_output_path, ri)

    if ri.has_error_registered():
        sys.exit(1)
