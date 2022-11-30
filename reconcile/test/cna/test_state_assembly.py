from typing import (
    Optional,
    cast,
)

import pytest

from reconcile.cna.assets.asset import (
    Asset,
    AssetStatus,
    AssetType,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import (
    CNAStateError,
    State,
)


def null_asset(name: str, addr_block: Optional[str] = None) -> NullAsset:
    return NullAsset(
        uuid=None,
        href=None,
        kind=AssetType.NULL,
        status=AssetStatus.RUNNING,
        name=name,
        addr_block=addr_block,
    )


def test_assemble_state_with_assets():
    state = State()
    assets = {
        "test": null_asset(
            name="test",
        ),
        "test2": null_asset(
            name="test2",
        ),
    }
    for asset in list(assets.values()):
        state.add_asset(asset)
    state.add_raw_data([])

    assert state == State(
        assets=cast(dict[AssetType, dict[str, Asset]], {AssetType.NULL: assets})
    )


def test_assemble_state_raw_data():
    state = State()
    data = [
        {
            "id": "123",
            "href": "/123",
            "status": "Terminated",
            "asset_type": "null",
            "name": "test",
        },
        {
            "id": "1233",
            "href": "/1234",
            "status": "Terminated",
            "asset_type": "null",
            "name": "test2",
            "addr_block": "1234",
        },
    ]
    assets = {
        AssetType.NULL: {
            asset.get("name", ""): NullAsset.from_api_mapping(asset) for asset in data
        }
    }
    state.add_raw_data(data)

    assert state == State(assets=cast(dict[AssetType, dict[str, Asset]], assets))


def test_assemble_raises_duplicate_error():
    state = State()
    null = null_asset(
        name="test",
    )
    assets = [null, null]
    with pytest.raises(CNAStateError) as err:
        for asset in assets:
            state.add_asset(asset)

    assert (
        str(err.value)
        == "Duplicate asset name found in state: kind=AssetType.NULL, name=test"
    )
