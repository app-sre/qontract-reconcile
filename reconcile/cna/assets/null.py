from __future__ import annotations
from pydantic.dataclasses import dataclass
from pydantic import Field
from typing import Optional

from reconcile.cna.assets.asset import (
    Asset,
    AssetType,
    AssetStatus,
    AssetModelConfig,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
)


@dataclass(frozen=True, config=AssetModelConfig)
class NullAsset(Asset[CNANullAssetV1]):
    addr_block: Optional[str] = Field(None, alias="AddrBlock")

    @staticmethod
    def provider() -> str:
        return "null-asset"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.NULL

    @staticmethod
    def from_query_class(asset: CNANullAssetV1) -> Asset:
        return NullAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            bindings=[],
            name=asset.identifier,
            addr_block=asset.overrides.addr_block if asset.overrides else None,
        )
