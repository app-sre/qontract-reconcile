from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.openshift_serviceaccount_tokens.tokens import NamespaceV1
from reconcile.openshift_serviceaccount_tokens import (
    canonicalize_namespaces,
    construct_sa_token_oc_resource,
    fetch_desired_state,
    get_serviceaccount_tokens,
    get_tokens_for_service_account,
    write_outputs_to_vault,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import OC_Map, OCCli
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.vault import _VaultClient


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("openshift_serviceaccount_tokens")


@pytest.fixture
def query_func(
    data_factory: Callable[[type[NamespaceV1], Mapping[str, Any]], Mapping[str, Any]],
    fx: Fixtures,
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "namespaces": [
                data_factory(NamespaceV1, item)
                for item in fx.get_anymarkup("namespaces.yml")["namespaces"]
            ]
        }

    return q


@pytest.fixture
def namespaces(query_func: Callable) -> list[NamespaceV1]:
    return get_serviceaccount_tokens(query_func)


@pytest.fixture
def ri(namespaces: list[NamespaceV1]) -> ResourceInventory:
    _ri = ResourceInventory()
    _ri.initialize_resource_type(
        cluster="cluster", namespace="namespace", resource_type="Secret"
    )
    for ns in namespaces:
        _ri.initialize_resource_type(
            cluster=ns.cluster.name, namespace=ns.name, resource_type="Secret"
        )
    return _ri


def test_openshift_serviceaccount_tokens__construct_sa_token_oc_resource() -> None:
    qr = construct_sa_token_oc_resource("foobar", "token")
    assert qr.body == {
        "apiVersion": "v1",
        "data": {"token": "token"},
        "kind": "Secret",
        "metadata": {"name": "foobar"},
        "type": "Opaque",
    }


def test_openshift_serviceaccount_tokens__get_tokens_for_service_account() -> None:
    foobar_secret = {
        "metadata": {
            "annotations": {"kubernetes.io/service-account.name": "foobar-account"}
        },
        "type": "kubernetes.io/service-account-token",
    }
    assert get_tokens_for_service_account(
        service_account="foobar-account",
        tokens=[
            foobar_secret,
            {
                "metadata": {
                    "annotations": {
                        "kubernetes.io/service-account.name": "just-another-account"
                    }
                },
                "type": "kubernetes.io/service-account-token",
            },
            foobar_secret,
            {
                "metadata": {"annotations": {"whatever": "foobar-account"}},
                "type": "not-a-service-account-token",
            },
        ],
    ) == [foobar_secret, foobar_secret]


def test_openshift_serviceaccount_tokens__write_outputs_to_vault(
    mocker: MockerFixture, ri: ResourceInventory
) -> None:
    vault_client = mocker.create_autospec(_VaultClient)

    ri.add_desired(
        cluster="cluster",
        namespace="namespace",
        resource_type="Secret",
        name="name",
        value=construct_sa_token_oc_resource("name", "token"),
    )
    write_outputs_to_vault(vault_client, "path/to/secrets", ri)
    vault_client.write.call_count == 2
    vault_client.write.assert_has_calls([
        call({
            "path": "path/to/secrets/openshift-serviceaccount-tokens/cluster/namespace/name",
            "data": {"token": "token"},
        }),
        call({
            "path": "path/to/secrets/openshift-serviceaccount-tokens/shared-resources/name",
            "data": {"token": "token"},
        }),
    ])


def test_openshift_serviceaccount_tokens__get_serviceaccount_tokens(
    namespaces: list[NamespaceV1],
) -> None:
    assert len(namespaces) == 3
    assert namespaces[0].name == "with-openshift-serviceaccount-tokens"
    assert namespaces[1].name == "with-shared-resources"
    assert (
        namespaces[2].name
        == "with-openshift-serviceaccount-tokens-and-shared-resources"
    )


def test_openshift_serviceaccount_tokens__canonicalize_namespaces(
    namespaces: list[NamespaceV1],
) -> None:
    nss = canonicalize_namespaces(namespaces)
    assert len(nss) == 6

    # 1st namespace in yaml
    nss[0].name == "with-openshift-serviceaccount-tokens"
    nss[0].cluster.name == "cluster"
    # must create this new namespace because of another referenced cluster
    nss[1].name == "with-openshift-serviceaccount-tokens"
    nss[1].cluster.name == "another-cluster"
    assert len(nss[0].openshift_service_account_tokens or []) == 2

    # 2nd namespace in yaml
    nss[2].name == "with-shared-resources"
    # shared resources must be resolved to openshift_service_account_tokens
    assert len(nss[2].openshift_service_account_tokens or []) == 1

    # 3rd namespace in yaml
    nss[4].name == "with-openshift-serviceaccount-tokens-and-shared-resources"
    # shared resources must be resolved to openshift_service_account_tokens
    assert len(nss[4].openshift_service_account_tokens or []) == 2


def test_openshift_serviceaccount_tokens__fetch_desired_state(
    mocker: MockerFixture, namespaces: list[NamespaceV1], ri: ResourceInventory
) -> None:
    grafana_secret = {
        "metadata": {
            "name": "grafana-secret",
            "annotations": {"kubernetes.io/service-account.name": "grafana"},
        },
        "type": "kubernetes.io/service-account-token",
        "data": {"token": "super-secret-token"},
    }

    oc_map = mocker.create_autospec(OC_Map)
    oc = mocker.create_autospec(OCCli)
    oc_map.get.return_value = oc
    oc.get_items.return_value = [
        grafana_secret,
        {
            "metadata": {
                "name": "just-another-account-secret",
                "annotations": {
                    "kubernetes.io/service-account.name": "just-another-account"
                },
            },
            "type": "kubernetes.io/service-account-token",
        },
        grafana_secret,
        {
            "metadata": {
                "name": "just-something-different",
                "annotations": {"whatever": "grafana"},
            },
            "type": "not-a-service-account-token",
        },
    ]
    fetch_desired_state(
        namespaces=namespaces,
        ri=ri,
        oc_map=oc_map,
    )
    assert (
        len(
            ri._clusters["cluster"]["with-openshift-serviceaccount-tokens"]["Secret"][
                "desired"
            ].keys()
        )
        == 2
    )
    assert (
        len(
            ri._clusters["cluster"][
                "with-openshift-serviceaccount-tokens-and-shared-resources"
            ]["Secret"]["desired"].keys()
        )
        == 1
    )
    assert (
        "another-cluster-with-openshift-serviceaccount-tokens-grafana"
        in ri._clusters["cluster"]["with-openshift-serviceaccount-tokens"]["Secret"][
            "desired"
        ]
    )
