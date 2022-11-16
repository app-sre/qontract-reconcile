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
from reconcile.cna.assets.asset_factory import asset_factory_from_raw_data
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import (
    CNAStateError,
    State,
)


def null_asset(name: str, addr_block: Optional[str] = None) -> NullAsset:
    return NullAsset(
        id=None,
        href=None,
        status=AssetStatus.RUNNING,
        name=name,
        addr_block=addr_block,
        bindings=set(),
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
    assets: dict[AssetType, dict[str, Asset]] = {
        AssetType.NULL: {
            raw_asset.get("name", ""): Asset.from_api_mapping(
                raw_asset,
                NullAsset,
            )
            for raw_asset in data
        }
    }
    for raw_asset in data:
        state.add_asset(asset_factory_from_raw_data(raw_asset))

    # todo check if cast is needed
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
        == "Duplicate asset name found in state: asset_type=null, name=test"
    )
