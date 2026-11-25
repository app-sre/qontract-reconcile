from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import reconcile.openshift_network_policies as sut
from reconcile.gql_definitions.openshift_network_policies.namespaces import NamespaceV1

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def namespaces(gql_class_factory: Callable[..., NamespaceV1]) -> list[NamespaceV1]:
    return [
        gql_class_factory(
            NamespaceV1,
            {
                "name": namespace,
                "cluster": {"name": cluster},
                "clusterAdmin": privileged,
                "delete": False,
                "networkPoliciesAllow": [
                    {"name": "monitoring", "cluster": {"name": cluster}}
                ],
            },
        )
        for cluster, namespace, privileged in [
            ("cluster-a", "tenant", True),
            ("cluster-b", "tenant", False),
            ("cluster-a", "ordinary", None),
        ]
    ]


@pytest.fixture
def runtime(
    mocker: MockerFixture,
    namespaces: list[NamespaceV1],
) -> tuple[MagicMock, dict[tuple[str, bool], MagicMock]]:
    api = mocker.patch.object(sut.gql, "get_api").return_value
    api.query.side_effect = lambda *args, **kwargs: {
        "namespaces": [ns.model_dump(by_alias=True) for ns in namespaces]
    }
    mocker.patch.object(sut, "is_in_shard", return_value=True)
    mocker.patch.object(sut.ob, "get_app_interface_vault_settings")
    mocker.patch.object(sut.ob, "create_secret_reader")
    oc_map = mocker.patch.object(sut.ob, "OC_Map").return_value
    clients = {
        (cluster, privileged): mocker.MagicMock()
        for cluster in ("cluster-a", "cluster-b")
        for privileged in (False, True)
    }
    owned = sut.construct_oc_resource("old-policy", "old-source").annotate()
    keep = sut.construct_oc_resource(
        "allow-from-monitoring-namespace", "monitoring"
    ).annotate()
    unowned = sut.construct_oc_resource("tenant-policy", "another-source")
    foreign = sut.construct_oc_resource("other-integration-policy", "another-source")
    foreign.integration = "other-integration"
    foreign = foreign.annotate()
    for client in clients.values():
        client.get_items.return_value = [
            r.body for r in (owned, keep, unowned, foreign)
        ]
    oc_map.get_cluster.side_effect = lambda cluster, privileged=False: clients[
        cluster, privileged
    ]
    return oc_map, clients


@pytest.mark.parametrize("dry_run", [False, True])
def test_cleanup_uses_namespace_auth(
    mocker: MockerFixture,
    namespaces: list[NamespaceV1],
    runtime: tuple[MagicMock, dict[tuple[str, bool], MagicMock]],
    dry_run: bool,
) -> None:
    _, clients = runtime
    realize = mocker.spy(sut.ob, "realize_data")

    sut.run(dry_run=dry_run, thread_pool_size=1)

    assert len(realize.spy_return) == len(namespaces)
    for ns in namespaces:
        action = next(
            a
            for a in realize.spy_return
            if (a["cluster"], a["namespace"]) == (ns.cluster.name, ns.name)
        )
        assert action == {
            "action": "deleted",
            "cluster": ns.cluster.name,
            "namespace": ns.name,
            "kind": "NetworkPolicy",
            "name": "old-policy",
            "privileged": bool(ns.cluster_admin),
        }
        selected = clients[ns.cluster.name, bool(ns.cluster_admin)]
        selected.get_items.assert_any_call(
            "NetworkPolicy", namespace=ns.name, resource_names=None
        )
        if not dry_run:
            selected.delete.assert_any_call(ns.name, "NetworkPolicy", "old-policy")
    assert sum(client.delete.call_count for client in clients.values()) == (
        0 if dry_run else len(namespaces)
    )
    assert clients["cluster-b", True].delete.call_count == 0


@pytest.mark.parametrize("reason", ["omitted", "empty", "deleted", "out-of-shard"])
def test_skipped_namespaces_are_not_discovered(
    mocker: MockerFixture,
    namespaces: list[NamespaceV1],
    runtime: tuple[MagicMock, dict[tuple[str, bool], MagicMock]],
    reason: str,
) -> None:
    oc_map, _ = runtime
    for ns in namespaces:
        if reason == "omitted":
            ns.network_policies_allow = None
        elif reason == "empty":
            ns.network_policies_allow = []
        elif reason == "deleted":
            ns.delete = True
    if reason == "out-of-shard":
        mocker.patch.object(sut, "is_in_shard", return_value=False)
    sut.run(dry_run=False, thread_pool_size=1)
    oc_map.get_cluster.assert_not_called()


def test_admin_namespace_keeps_desired_policy_without_ordinary_client(
    namespaces: list[NamespaceV1],
    runtime: tuple[MagicMock, dict[tuple[str, bool], MagicMock]],
) -> None:
    del namespaces[1:]
    oc_map, clients = runtime
    oc_map.get.side_effect = lambda cluster, privileged=False: (
        clients[cluster, True] if privileged else None
    )
    sut.run(dry_run=False, thread_pool_size=1)
    clients["cluster-a", True].delete.assert_called_once_with(
        "tenant", "NetworkPolicy", "old-policy"
    )


def test_cross_cluster_grant_disables_cleanup(
    namespaces: list[NamespaceV1],
    runtime: tuple[MagicMock, dict[tuple[str, bool], MagicMock]],
) -> None:
    _, clients = runtime
    for ns in namespaces:
        assert ns.network_policies_allow
        ns.network_policies_allow[0].cluster.name = "another-cluster"
    with pytest.raises(SystemExit) as exc:
        sut.run(dry_run=False, thread_pool_size=1)
    assert exc.value.code == 1
    for client in clients.values():
        client.delete.assert_not_called()
