from typing import Any, Iterable, Mapping
from unittest.mock import create_autospec
from pytest import fixture
import pytest
from reconcile.cna.client import CNAClient
from reconcile.cna.integration import CNAIntegration
from reconcile.cna.assets.asset import AssetStatus, AssetType
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import State


@fixture
def cna_clients() -> dict[str, CNAClient]:
    cna_client = create_autospec(CNAClient)
    return {
        "test": cna_client,
    }


@pytest.mark.parametrize(
    "listed_assets, expected_state",
    [
        (
            # Empty state
            [],
            State(assets={AssetType.NULL: {}}),
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
                }
            ],
            State(
                assets={
                    AssetType.NULL: {
                        "null-test": NullAsset(
                            uuid="123",
                            status=AssetStatus.RUNNING,
                            name="null-test",
                            kind=AssetType.NULL,
                            href="url/123",
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
                },
                {
                    "asset_type": "null",
                    "id": "456",
                    "href": "url/456",
                    "status": "Running",
                    "name": "null-test2",
                },
            ],
            State(
                assets={
                    AssetType.NULL: {
                        "null-test": NullAsset(
                            uuid="123",
                            status=AssetStatus.RUNNING,
                            name="null-test",
                            kind=AssetType.NULL,
                            href="url/123",
                            addr_block=None,
                        ),
                        "null-test2": NullAsset(
                            uuid="456",
                            status=AssetStatus.RUNNING,
                            name="null-test2",
                            kind=AssetType.NULL,
                            href="url/456",
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
def test_integration_assemble_actual_states(
    cna_clients: Mapping[str, CNAClient],
    listed_assets: Iterable[Mapping[str, Any]],
    expected_state: State,
):
    cna_clients["test"].list_assets.side_effect = [listed_assets]  # type: ignore
    integration = CNAIntegration(cna_clients=cna_clients, namespaces=[])
    integration.assemble_actual_states()
    assert integration._actual_states == {"test": expected_state}


def test_integration_assemble_desired_states():
    pass
