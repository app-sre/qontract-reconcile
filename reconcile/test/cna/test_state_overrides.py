from typing import Optional
import pytest

from reconcile.cna.assets.asset import AssetStatus, AssetType
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import State


def null_asset(
    name: str,
    href: Optional[str] = None,
    uuid: Optional[str] = None,
    addr_block: Optional[str] = None,
    status: Optional[AssetStatus] = None,
) -> NullAsset:
    return NullAsset(
        uuid=uuid,
        href=href,
        kind=AssetType.NULL,
        status=status,
        name=name,
        addr_block=addr_block,
    )


@pytest.mark.parametrize(
    "a, b",
    [
        (
            # Empty states are equal
            State(assets={}),
            State(assets={}),
        ),
        (
            # Status does not count towards equality
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            status=AssetStatus.RUNNING,
                        ),
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            status=AssetStatus.TERMINATED,
                        ),
                    }
                }
            ),
        ),
        (
            # uuid and href do not count towards equality
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            status=AssetStatus.RUNNING,
                        ),
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            uuid="123",
                            href="/123",
                        ),
                    }
                }
            ),
        ),
    ],
    ids=[
        "Empty states are equal",
        "Status does not count towards equality",
        "uuid and href do not count towards equality",
    ],
)
def test_state_eq(a: State, b: State):
    assert a == b


@pytest.mark.parametrize(
    "a, b",
    [
        (
            # single element with different attribute
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            status=AssetStatus.RUNNING,
                        ),
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                        "test2": null_asset(
                            name="test2",
                            addr_block="123",
                        ),
                    }
                }
            ),
        ),
        (
            # different elements
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        ),
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test2": null_asset(
                            name="test2",
                            uuid="123",
                            href="/123",
                        ),
                    }
                }
            ),
        ),
    ],
    ids=[
        "single element with different attribute",
        "different elements",
    ],
)
def test_state_ne(a: State, b: State):
    assert a != b


def test_state_iter():
    assets = [
        null_asset(
            name="test",
        ),
        null_asset(
            name="test2",
        ),
    ]
    state = State(assets={AssetType.NULL: {asset.name: asset for asset in assets}})
    iterated_assets = [asset for asset in state]

    assert len(assets) == len(iterated_assets)
    assert set(assets) == set(iterated_assets)
