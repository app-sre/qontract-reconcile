from typing import Any, Optional
from collections.abc import Iterable, Mapping
from unittest.mock import create_autospec
from pytest import fixture
import pytest
from reconcile.cna.client import CNAClient
from reconcile.cna.integration import CNAIntegration
from reconcile.cna.assets.asset import (
    AssetStatus,
    AssetType,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import State
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
    CNANullAssetOverridesV1,
    ExternalResourcesProvisionerV1,
    NamespaceCNAssetV1,
    ClusterV1,
    NamespaceV1,
)
from reconcile.utils.external_resources import PROVIDER_CNA_EXPERIMENTAL


@fixture
def cna_clients() -> dict[str, CNAClient]:
    cna_client = create_autospec(CNAClient)
    return {
        "test": cna_client,
    }


def namespace(assets: list[CNANullAssetV1]) -> NamespaceV1:
    return NamespaceV1(
        name="test",
        cluster=ClusterV1(spec=None),
        managedExternalResources=True,
        externalResources=[
            NamespaceCNAssetV1(
                provider=PROVIDER_CNA_EXPERIMENTAL,
                provisioner=ExternalResourcesProvisionerV1(
                    name="test",
                ),
                resources=assets,
            )
        ],
    )


def null_asset(name: str, addr_block: Optional[str]) -> NullAsset:
    return NullAsset(
        id=None,
        href=None,
        status=None,
        bindings=set(),
        name=name,
        addr_block=addr_block,
    )


@pytest.mark.parametrize(
    "listed_assets, expected_state",
    [
        (
            # Empty state
            [],
            State(),
        ),
        (
            # Single asset
            [
                {
                    "asset_type": "null",
                    "id": "123",
                    "href": "url/123",
                    "status": "Running",
                    "name": "null-test",
                    "parameters": {},
                    "creator": {"username": "creator"},
                }
            ],
            State(
                assets={
                    AssetType.NULL: {
                        "null-test": NullAsset(
                            id="123",
                            status=AssetStatus.RUNNING,
                            name="null-test",
                            href="url/123",
                            bindings=set(),
                            addr_block=None,
                        )
                    }
                }
            ),
        ),
        (
            # Multiple assets
            [
                {
                    "asset_type": "null",
                    "id": "123",
                    "href": "url/123",
                    "status": "Running",
                    "name": "null-test",
                    "creator": {"username": "creator"},
                },
                {
                    "asset_type": "null",
                    "id": "456",
                    "href": "url/456",
                    "status": "Running",
                    "name": "null-test2",
                    "creator": {"username": "creator"},
                },
            ],
            State(
                assets={
                    AssetType.NULL: {
                        "null-test": NullAsset(
                            id="123",
                            status=AssetStatus.RUNNING,
                            name="null-test",
                            href="url/123",
                            bindings=set(),
                            addr_block=None,
                        ),
                        "null-test2": NullAsset(
                            id="456",
                            status=AssetStatus.RUNNING,
                            name="null-test2",
                            href="url/456",
                            bindings=set(),
                            addr_block=None,
                        ),
                    }
                }
            ),
        ),
    ],
    ids=[
        "Empty states",
        "Single asset",
        "Multiple assets",
    ],
)
def test_integration_assemble_current_states(
    mocker,
    listed_assets: Iterable[Mapping[str, Any]],
    expected_state: State,
):
    mocker.patch.object(
        CNAClient, "list_assets", create_autospec=True, return_value=listed_assets
    )
    mocker.patch.object(
        CNAClient,
        "fetch_bindings_for_asset",
        create_autospec=True,
        return_value=[],
    )
    mocker.patch.object(
        CNAClient, "service_account_name", create_autospec=True, return_value="creator"
    )
    integration = CNAIntegration(cna_clients={"test": CNAClient(None)}, namespaces=[])  # type: ignore
    integration.assemble_current_states()
    assert integration._current_states == {"test": expected_state}


@pytest.mark.parametrize(
    "namespaces, expected_state",
    [
        (
            # Single asset
            [
                namespace(
                    assets=[
                        CNANullAssetV1(
                            provider="null-asset",
                            identifier="test",
                            overrides=CNANullAssetOverridesV1(
                                addr_block="123",
                            ),
                        )
                    ]
                )
            ],
            State(
                assets={
                    AssetType.NULL: {"test": null_asset(name="test", addr_block="123")}
                }
            ),
        ),
        (
            # Multiple assets
            [
                namespace(
                    assets=[
                        CNANullAssetV1(
                            provider="null-asset",
                            identifier="test",
                            overrides=CNANullAssetOverridesV1(
                                addr_block="123",
                            ),
                        ),
                        CNANullAssetV1(
                            provider="null-asset", identifier="test2", overrides=None
                        ),
                    ]
                )
            ],
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(name="test", addr_block="123"),
                        "test2": null_asset(name="test2", addr_block=None),
                    }
                }
            ),
        ),
    ],
    ids=[
        "Single asset",
        "Multiple assets",
    ],
)
def test_integration_assemble_desired_states(
    cna_clients: Mapping[str, CNAClient],
    namespaces: list[NamespaceV1],
    expected_state: State,
):
    integration = CNAIntegration(cna_clients=cna_clients, namespaces=namespaces)
    integration.assemble_desired_states()
    assert integration._desired_states == {"test": expected_state}
