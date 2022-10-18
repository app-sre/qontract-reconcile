from __future__ import annotations
from typing import Any, Iterable, Mapping
from reconcile.cna.assets import Asset, AssetStatus, NullAsset


class State:
    def __init__(self):
        self._null_assets: dict[str, NullAsset] = {}

    def add_null_asset(self, asset: NullAsset):
        self._null_assets[asset.name] = asset

    def add_raw_data(self, data: Iterable[Mapping[str, Any]]):
        for cna in data:
            if cna.get("asset_type") == "null":
                asset = NullAsset.from_api_mapping(cna)
                self._null_assets[asset.name] = asset

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
        for asset_name, asset in self._null_assets.items():
            if asset.status in (AssetStatus.TERMINATED, AssetStatus.PENDING):
                continue
            if asset_name in other._null_assets:
                continue
            ans.add_null_asset(asset)
        return ans

    def __iter__(self) -> State:
        self._i = 0
        self._all_assets = list(self._null_assets.values())
        return self

    def __next__(self) -> Asset:
        if self._i < len(self._all_assets):
            self._i += 1
            return self._all_assets[self._i - 1]
        else:
            raise StopIteration
