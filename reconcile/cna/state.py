from __future__ import annotations
from typing import Optional
from reconcile.cna.assets.asset import Asset, AssetStatus, AssetType, Binding


class CNAStateError(Exception):
    pass


class State:
    """
    State object is a collection of assets.
    It can be used to describe actual or desired state.
    Main objective is to calculate required additions,
    deletions and updates to reach another state.
    """

    def __init__(self, assets: Optional[dict[AssetType, dict[str, Asset]]] = None):
        self._assets: dict[AssetType, dict[str, Asset]] = {}
        if assets:
            self._assets = assets
        for asset_type in AssetType:
            if asset_type not in self._assets:
                self._assets[asset_type] = {}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, State):
            return False
        if not set(list(self._assets.keys())) == set(list(other._assets.keys())):
            return False
        for asset_type in list(self._assets.keys()):
            if not set(list(self._assets[asset_type])) == set(
                list(other._assets[asset_type])
            ):
                return False
            for name, asset in self._assets[asset_type].items():
                if (
                    asset.asset_properties()
                    != other._assets[asset_type][name].asset_properties()
                ):
                    return False
        return True

    def __repr__(self) -> str:
        # pytest should show nice diff
        return str(self._assets)

    def _validate_addition(self, asset: Asset):
        asset_type = asset.asset_type()
        if asset_type not in self._assets:
            raise CNAStateError(f"State doesn't know asset_type {asset_type}")
        if asset.name in self._assets[asset_type]:
            raise CNAStateError(
                f"Duplicate asset name found in state: asset_type={asset_type}, name={asset.name}"
            )

    def contains(self, asset: Asset) -> bool:
        return asset.name in self._assets[asset.asset_type()]

    def add_asset(self, asset: Asset):
        self._validate_addition(asset=asset)
        self._assets[asset.asset_type()][asset.name] = asset

    def _diff(self, other: State, compare_bindings: bool) -> State:
        """
        This operation is NOT commutative, i.e.,:
        a._diff(b) != b._diff(a)

        This is supposed to be used on actual state (self).
        I.e., actual._diff(desired) is supposed to show diff
        from actual to reach desired.
        """
        ans = State()
        for asset_type in AssetType:
            for asset_name, other_asset in other._assets[asset_type].items():
                if asset_name not in self._assets[asset_type]:
                    continue
                asset = self._assets[asset_type][asset_name]
                if asset.status in (AssetStatus.TERMINATED, AssetStatus.PENDING):
                    continue
                required_bindings: set[Binding] = set()
                if compare_bindings:
                    for binding in other_asset.bindings:
                        if binding not in asset.bindings:
                            required_bindings.add(binding)
                    if not required_bindings:
                        # Bindings are the same - no need to bind
                        continue
                else: 
                    if asset.asset_properties() == other_asset.asset_properties():
                        # There is no diff - no need to update
                        continue
                updated_asset = asset.update_from(other_asset)
                if compare_bindings:
                    # We want to make sure the missing bindings are created
                    updated_asset.bindings.clear()
                    for binding in required_bindings:
                        updated_asset.bindings.add(binding)
                ans.add_asset(asset=updated_asset)
        return ans

    def required_updates_to_reach(self, other: State) -> State:
        return self._diff(other=other, compare_bindings=False)

    def required_bindings_to_reach(self, other: State) -> State:
        return self._diff(other=other, compare_bindings=True)

    def get_terminated_assets(self) -> list[Asset]:
        """
        Return a list of assets in terminated state.
        Those should be deleted again to be purged.
        """
        return [asset for asset in self if asset.status == AssetStatus.TERMINATED]

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
        for asset_type in AssetType:
            for asset_name, asset in self._assets[asset_type].items():
                if asset.status in (AssetStatus.TERMINATED, AssetStatus.PENDING):
                    continue
                if other_asset := other._assets[asset_type].get(asset_name):
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
        for asset_type in AssetType:
            self._assets_list += list(self._assets[asset_type].values())
        return self

    def __next__(self) -> Asset:
        if self._i < len(self._assets_list):
            self._i += 1
            return self._assets_list[self._i - 1]
        else:
            raise StopIteration
