from __future__ import annotations

from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

from reconcile.cna.assets.asset import (
    Asset,
    AssetStatus,
    AssetType,
)
from reconcile.cna.assets.asset_factory import asset_factory_from_raw_data


class CNAStateError(Exception):
    pass


class State:
    """
    State object is a collection of assets.
    It can be used to describe actual or desired state.
    Main objective is to calculate required additions,
    deletions and updates to reach another state.
    """

    def __init__(self, assets: dict[AssetType, dict[str, Asset]] | None = None):
        self._assets: dict[AssetType, dict[str, Asset]] = {}
        for kind in AssetType:
            self._assets[kind] = {}
        if assets:
            self._assets = assets

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, State):
            return False
        if not set(list(self._assets.keys())) == set(list(other._assets.keys())):
            return False
        for kind in list(self._assets.keys()):
            if not set(list(self._assets[kind])) == set(list(other._assets[kind])):
                return False
            for name, asset in self._assets[kind].items():
                if asset != other._assets[kind][name]:
                    return False
        return True

    def __repr__(self) -> str:
        # pytest should show nice diff
        return str(self._assets)

    def _validate_addition(self, asset: Asset):
        if asset.kind not in self._assets:
            raise CNAStateError(f"State doesn't know asset_kind {asset.kind}")
        if asset.name in self._assets[asset.kind]:
            raise CNAStateError(
                f"Duplicate asset name found in state: kind={asset.kind}, name={asset.name}"
            )

    def add_asset(self, asset: Asset):
        self._validate_addition(asset=asset)
        self._assets[asset.kind][asset.name] = asset

    def add_raw_data(self, data: Iterable[Mapping[str, Any]]):
        for cna in data:
            asset = asset_factory_from_raw_data(cna)
            self._validate_addition(asset=asset)
            self._assets[asset.kind][asset.name] = asset

    def required_updates_to_reach(self, other: State) -> State:
        """
        This operation is NOT commutative, i.e.,:
        a.required_updates_to_reach(b) != b.required_updates_to_reach(a)

        This is supposed to be called on actual state (self).
        I.e., actual.required_updates_to_reach(desired)
        """
        ans = State()
        for kind in AssetType:
            for asset_name, other_asset in other._assets[kind].items():
                if asset_name not in self._assets[kind]:
                    continue
                asset = self._assets[kind][asset_name]
                if asset.status in {AssetStatus.TERMINATED, AssetStatus.PENDING}:
                    continue
                if asset == other_asset:
                    # There is no diff - no need to update
                    continue
                ans.add_asset(asset=asset.update_from(other_asset))
        return ans

    def __sub__(self, other: State) -> State:
        """
        This is used to determine creations and deletions
        of assets. We only check the existance of the name
        in each state. TERMINATED and PENDING assets are
        omitted.

        additions = self - other
        deletions = other - self
        """
        ans = State()
        for kind in AssetType:
            for asset_name, asset in self._assets[kind].items():
                if asset.status in {AssetStatus.TERMINATED, AssetStatus.PENDING}:
                    continue
                if other_asset := other._assets[kind].get(asset_name):
                    if other_asset.status == AssetStatus.TERMINATED:
                        raise CNAStateError(
                            f"Trying to create/update terminated asset {asset}. Currently not possible."
                        )
                    continue
                ans.add_asset(asset)
        return ans

    def __iter__(self) -> State:
        self._i = 0
        self._assets_list: list[Asset] = []
        for kind in AssetType:
            self._assets_list += list(self._assets[kind].values())
        return self

    def __next__(self) -> Asset:
        if self._i < len(self._assets_list):
            self._i += 1
            return self._assets_list[self._i - 1]
        raise StopIteration
