from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

import reconcile.openshift_network_policies as sut
from reconcile.gql_definitions.openshift_network_policies.namespaces import (
    NamespaceV1,
    NetworkPolicyAllowRuleV1,
    NetworkPolicyNamespacePeerV1,
)
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceKeyExistsError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def namespace(data_factory: Callable, rule: NetworkPolicyAllowRuleV1) -> NamespaceV1:
    result = NamespaceV1.model_validate(
        data_factory(
            NamespaceV1,
            {
                "name": "tenant",
                "cluster": {"name": "cluster", "serverUrl": "https://example.com"},
            },
        )
    )
    result.network_policies_allow = [
        NetworkPolicyNamespacePeerV1.model_validate({
            "entry_schema": "/openshift/namespace-1.yml",
            "name": "monitoring",
            "cluster": {"name": "cluster"},
        }),
        rule,
    ]
    return result


@pytest.fixture
def rule(data_factory: Callable) -> NetworkPolicyAllowRuleV1:
    return NetworkPolicyAllowRuleV1.model_validate(
        data_factory(
            NetworkPolicyAllowRuleV1,
            {
                "entry_schema": "/openshift/network-policy-rule-1.yml",
                "name": "consumer-metrics",
                "namespace": {"name": "monitoring", "cluster": {"name": "cluster"}},
                "podSelector": {
                    "matchLabels": json.dumps({"app": "kessel-inventory-consumer"})
                },
                "sourcePodSelector": {
                    "matchLabels": json.dumps({"prometheus": "app-sre"})
                },
                "ports": [{"port": 9000, "protocol": "TCP"}],
            },
        )
    )


@pytest.fixture
def ri(namespace: NamespaceV1) -> ResourceInventory:
    inventory = ResourceInventory()
    inventory.initialize_resource_type(
        namespace.cluster.name, namespace.name, "NetworkPolicy"
    )
    return inventory


@pytest.fixture
def oc_map(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(OC_Map)


@pytest.fixture
def mock_runtime(
    mocker: MockerFixture,
    namespace: NamespaceV1,
    ri: ResourceInventory,
    oc_map: MagicMock,
) -> MagicMock:
    api = mocker.patch.object(sut.gql, "get_api").return_value
    api.query.side_effect = lambda _: {
        "namespaces": [namespace.model_dump(by_alias=True, round_trip=True)]
    }
    mocker.patch.object(sut, "is_in_shard", return_value=True)
    mocker.patch.object(sut.ob, "publish_metrics")
    return mocker.patch.object(sut.ob, "fetch_current_state", return_value=(ri, oc_map))


def test_mixed_entries(
    namespace: NamespaceV1,
    ri: ResourceInventory,
    oc_map: MagicMock,
    mock_runtime: MagicMock,
) -> None:
    namespace.cluster_admin = True
    sut.run(dry_run=True, thread_pool_size=1)
    policies = ri.get_desired_by_type("cluster", "tenant", "NetworkPolicy")
    assert policies is not None
    assert set(policies) == {"allow-from-monitoring-namespace", "consumer-metrics"}
    assert policies["allow-from-monitoring-namespace"].body["spec"] == {
        "podSelector": {},
        "policyTypes": ["Ingress"],
        "ingress": [
            {
                "from": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "monitoring"}
                        }
                    }
                ]
            }
        ],
    }
    assert policies["consumer-metrics"].body["spec"] == {
        "podSelector": {"matchLabels": {"app": "kessel-inventory-consumer"}},
        "policyTypes": ["Ingress"],
        "ingress": [
            {
                "from": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "monitoring"}
                        },
                        "podSelector": {"matchLabels": {"prometheus": "app-sre"}},
                    }
                ],
                "ports": [{"port": 9000, "protocol": "TCP"}],
            }
        ],
    }
    for _, _, _, state in ri:
        assert all(state["use_admin_token"].values())
    assert mock_runtime.call_args.kwargs["namespaces"][0]["name"] == "tenant"
    oc_map.get_cluster.return_value.apply.assert_not_called()


def test_ports_without_pod_selectors(rule: NetworkPolicyAllowRuleV1) -> None:
    rule.pod_selector = None
    rule.source_pod_selector = None
    assert rule.ports
    rule.ports[0].protocol = None
    rule.ports.append(
        rule.ports[0].model_copy(update={"port": 9001, "protocol": "UDP"})
    )
    spec = sut.construct_oc_resource(rule.name, rule.namespace.name, rule).body["spec"]
    assert spec["podSelector"] == {}
    assert "podSelector" not in spec["ingress"][0]["from"][0]
    assert spec["ingress"][0]["ports"] == [
        {"port": 9000, "protocol": "TCP"},
        {"port": 9001, "protocol": "UDP"},
    ]


def test_empty_selectors_and_omitted_ports_are_unrestricted(
    rule: NetworkPolicyAllowRuleV1,
) -> None:
    assert rule.pod_selector is not None
    assert rule.source_pod_selector is not None
    rule.pod_selector.match_labels = None
    rule.source_pod_selector.match_labels = None
    rule.ports = None
    spec = sut.construct_oc_resource(rule.name, rule.namespace.name, rule).body["spec"]
    assert spec["podSelector"] == {}
    assert spec["ingress"][0]["from"][0]["podSelector"] == {}
    assert "ports" not in spec["ingress"][0]


@pytest.mark.parametrize("entry_index", [0, 1], ids=["namespace", "rule"])
def test_cross_cluster_grants_are_rejected(
    namespace: NamespaceV1,
    ri: ResourceInventory,
    entry_index: int,
    mock_runtime: MagicMock,
) -> None:
    assert namespace.network_policies_allow
    entry = namespace.network_policies_allow[entry_index]
    if isinstance(entry, NetworkPolicyNamespacePeerV1):
        entry.cluster.name = "other-cluster"
    else:
        assert isinstance(entry, NetworkPolicyAllowRuleV1)
        entry.namespace.cluster.name = "other-cluster"
    namespace.network_policies_allow = [entry]
    with pytest.raises(SystemExit, match="1"):
        sut.run(dry_run=True, thread_pool_size=1)
    mock_runtime.assert_called_once()
    assert ri.has_error_registered()
    assert not ri.get_desired_by_type("cluster", "tenant", "NetworkPolicy")


@pytest.mark.parametrize("invalid", ["empty-ports", "duplicate-name"])
def test_invalid_rules_abort_before_mutations(
    rule: NetworkPolicyAllowRuleV1,
    oc_map: MagicMock,
    mock_runtime: MagicMock,
    invalid: str,
) -> None:
    error: type[Exception]
    if invalid == "empty-ports":
        rule.ports = []
        error = ValueError
    else:
        rule.name = "allow-from-monitoring-namespace"
        error = ResourceKeyExistsError
    with pytest.raises(error):
        sut.run(dry_run=False, thread_pool_size=1)
    mock_runtime.assert_called_once()
    oc_map.get_cluster.return_value.apply.assert_not_called()
    oc_map.get_cluster.return_value.delete.assert_not_called()


def test_explicit_empty_list_only_deletes_owned_policy(
    namespace: NamespaceV1,
    ri: ResourceInventory,
    oc_map: MagicMock,
    mock_runtime: MagicMock,
) -> None:
    namespace.network_policies_allow = []
    owned = sut.construct_oc_resource("old-metrics", "monitoring").annotate()
    unowned = sut.construct_oc_resource("tenant-owned", "monitoring")
    for resource in (owned, unowned):
        ri.add_current("cluster", "tenant", "NetworkPolicy", resource.name, resource)
    sut.run(dry_run=False, thread_pool_size=1)
    assert mock_runtime.call_args.kwargs["namespaces"][0]["networkPoliciesAllow"] == []
    oc_map.get_cluster.return_value.delete.assert_called_once_with(
        "tenant", "NetworkPolicy", "old-metrics"
    )


@pytest.mark.parametrize("reason", ["omitted", "deleted", "other-shard"])
def test_skipped_namespaces_do_not_initialize_clients(
    mocker: MockerFixture,
    namespace: NamespaceV1,
    mock_runtime: MagicMock,
    reason: str,
) -> None:
    if reason == "omitted":
        namespace.network_policies_allow = None
    elif reason == "deleted":
        namespace.delete = True
    else:
        mocker.patch.object(sut, "is_in_shard", return_value=False)
    sut.run(dry_run=True)
    mock_runtime.assert_not_called()
