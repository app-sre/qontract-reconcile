from typing import Optional

import pytest

from reconcile.cna.assets.asset import (
    AssetStatus,
    AssetType,
)
from reconcile.cna.assets.null import NullAsset
from reconcile.cna.state import (
    CNAStateError,
    State,
)


def null_asset(
    name: str,
    status: Optional[AssetStatus] = None,
    addr_block: Optional[str] = None,
    id: Optional[str] = None,
) -> NullAsset:
    return NullAsset(
        id=id,
        href=None,
        status=status,
        addr_block=addr_block,
        bindings=set(),
        name=name,
    )


@pytest.mark.parametrize(
    "desired, current, expected_additions, expected_deletions, expected_updates",
    [
        (
            # Empty states
            State(assets={}),
            State(assets={}),
            State(assets={}),
            State(assets={}),
            State(assets={}),
        ),
        (
            # Add resource to empty state
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(assets={}),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(assets={}),
            State(assets={}),
        ),
        (
            # Do not add/update already existing resource
            State(
                assets={
                    AssetType.NULL: {"test": null_asset(name="test", addr_block="addr")}
                }
            ),
            State(
                assets={
                    AssetType.NULL: {"test": null_asset(name="test", addr_block="addr")}
                }
            ),
            State(assets={}),
            State(assets={}),
            State(assets={}),
        ),
        (
            # Delete non desired resource
            State(assets={}),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(assets={}),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(assets={}),
        ),
        (
            # Delete and create resources
            State(
                assets={
                    AssetType.NULL: {
                        "test2": null_asset(
                            name="test2",
                        )
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test2": null_asset(
                            name="test2",
                        )
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                        )
                    }
                }
            ),
            State(assets={}),
        ),
        (
            # Delete, create and update resources
            State(  # desired
                assets={
                    AssetType.NULL: {
                        "test1": null_asset(
                            name="test1",
                            addr_block="123",
                        ),
                        "test2": null_asset(
                            name="test2",
                        ),
                    }
                }
            ),
            State(  # current
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                            id="test",
                        ),
                        "test1": null_asset(
                            name="test1",
                            id="test1",
                        ),
                    }
                }
            ),
            State(  # expected additions
                assets={
                    AssetType.NULL: {
                        "test2": null_asset(
                            name="test2",
                        )
                    }
                }
            ),
            State(  # expected deletions
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                            id="test",
                        )
                    }
                }
            ),
            State(  # expected updates
                assets={
                    AssetType.NULL: {
                        "test1": null_asset(
                            name="test1",
                            addr_block="123",
                            id="test1",
                        )
                    }
                }
            ),
        ),
        (
            # Ignore TERMINATED and PENDING
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                            addr_block="123",
                        )
                    }
                }
            ),
            State(
                assets={
                    AssetType.NULL: {
                        "test": null_asset(
                            name="test",
                            status=AssetStatus.PENDING,
                        ),
                        "test1": null_asset(
                            name="test1",
                            status=AssetStatus.TERMINATED,
                        ),
                    }
                }
            ),
            State(assets={}),
            State(assets={}),
            State(assets={}),
        ),
    ],
    ids=[
        "Empty states",
        "Add resource to empty state",
        "Do not add/update already existing resource",
        "Delete non desired resource",
        "Delete and create resources",
        "Delete, create and update resources",
        "Ignore TERMINATED and PENDING",
    ],
)
def test_state_create_delete_update(
    desired: State,
    current: State,
    expected_additions: State,
    expected_deletions: State,
    expected_updates: State,
):
    additions = desired - current
    deletions = current - desired
    updates = current.required_updates_to_reach(desired)
    assert additions == expected_additions
    assert deletions == expected_deletions
    assert updates == expected_updates

    for update, expected_update in zip(updates, expected_updates):
        """
        The update should contain the uuid of the actual asset.
        Currently CNA does not support addressing w/o use of
        internal uuid.
        """
        assert update.id == expected_update.id


def test_state_create_update_terminated():
    """
    Throw an error when trying to update/create TERMINATED resource
    This is a current limitation of CNA and will be fixed in the future.
    """
    desired = State(
        assets={
            AssetType.NULL: {
                "test": null_asset(
                    name="test",
                )
            }
        }
    )
    actual = State(
        assets={
            AssetType.NULL: {
                "test": null_asset(
                    name="test",
                    id="test",
                    status=AssetStatus.TERMINATED,
                )
            }
        }
    )
    expected_err = CNAStateError(
        f"Trying to create/update terminated asset {null_asset(name='test')}. Currently not possible."
    )
    with pytest.raises(CNAStateError) as e:
        desired - actual

    assert str(e.value) == str(expected_err)
