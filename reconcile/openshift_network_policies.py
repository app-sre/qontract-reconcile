from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, cast

import reconcile.openshift_base as ob
from reconcile.gql_definitions.openshift_network_policies import (
    namespaces as namespaces_query,
)
from reconcile.utils import gql
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from reconcile.gql_definitions.openshift_network_policies.namespaces import (
        NamespaceV1,
        NetworkPolicyAllowRuleV1,
        NetworkPolicyNamespacePeerV1,
    )

QONTRACT_INTEGRATION = "openshift-network-policies"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_oc_resource(
    name: str, source_ns: str, rule: NetworkPolicyAllowRuleV1 | None = None
) -> OR:
    if rule is not None and rule.ports == []:
        raise ValueError(
            f"NetworkPolicy {name}: ports must not be empty; omit ports to allow all ports"
        )
    body: dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name},
        "spec": {
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": source_ns
                                }
                            }
                        }
                    ]
                }
            ],
            "podSelector": {},
            "policyTypes": ["Ingress"],
        },
    }
    if rule:
        if rule.pod_selector is not None:
            body["spec"]["podSelector"] = rule.pod_selector.model_dump(
                by_alias=True, exclude_none=True
            )
        if rule.source_pod_selector is not None:
            body["spec"]["ingress"][0]["from"][0]["podSelector"] = (
                rule.source_pod_selector.model_dump(by_alias=True, exclude_none=True)
            )
        if rule.ports is not None:
            body["spec"]["ingress"][0]["ports"] = [
                {"port": port.port, "protocol": port.protocol or "TCP"}
                for port in rule.ports
            ]
    return OR(
        body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
    )


def fetch_desired_state(
    namespaces: Iterable[NamespaceV1],
    ri: ResourceInventory,
    oc_map: ob.ClusterMap,
) -> None:
    for namespace_info in namespaces:
        namespace = namespace_info.name
        cluster = namespace_info.cluster.name
        if not oc_map.get(cluster):
            continue
        resources = []
        for entry in namespace_info.network_policies_allow or []:
            match entry.entry_schema:
                case "/openshift/namespace-1.yml":
                    source = cast("NetworkPolicyNamespacePeerV1", entry)
                    resource = construct_oc_resource(
                        f"allow-from-{source.name}-namespace", source.name
                    )
                    resources.append((resource, source.cluster.name))
                case "/openshift/network-policy-rule-1.yml":
                    rule = cast("NetworkPolicyAllowRuleV1", entry)
                    resources.append((
                        construct_oc_resource(rule.name, rule.namespace.name, rule),
                        rule.namespace.cluster.name,
                    ))
                case _:
                    raise ValueError(
                        f"Unsupported network policy entry: {entry.entry_schema}"
                    )
        for oc_resource, source_cluster in resources:
            if cluster != source_cluster:
                ri.register_error()
                msg = f"[{cluster}/{namespace}] Network Policy from cluster '{source_cluster}' not allowed."
                logging.error(msg)
                continue
            ri.add_desired(
                cluster,
                namespace,
                "NetworkPolicy",
                oc_resource.name,
                oc_resource,
                privileged=namespace_info.cluster_admin or False,
            )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    defer: Callable | None = None,
) -> None:
    gqlapi = gql.get_api()

    namespaces = []
    query_data = namespaces_query.query(query_func=gqlapi.query)
    for namespace_info in query_data.namespaces or []:
        if namespace_info.network_policies_allow is None:
            continue
        if namespace_info.delete:
            continue

        shard_key = f"{namespace_info.cluster.name}/{namespace_info.name}"

        if not is_in_shard(shard_key):
            continue

        namespaces.append(namespace_info)

    if not namespaces:
        logging.debug("No namespaces with network-policy grants to reconcile.")
        return

    ri, oc_map = ob.fetch_current_state(
        namespaces=[ns.model_dump(by_alias=True) for ns in namespaces],
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["NetworkPolicy"],
        internal=internal,
    )
    if defer:
        defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
