from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic.dataclasses import dataclass

from reconcile.cna.assets.asset import (
    Asset,
    AssetModelConfig,
    AssetStatus,
    AssetType,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetConfigV1,
    CNANullAssetV1,
)


@dataclass(frozen=True, config=AssetModelConfig)
class NullAsset(Asset[CNANullAssetV1, CNANullAssetConfigV1]):
    addr_block: Optional[str] = Field(None, alias="AddrBlock")

    @staticmethod
    def provider() -> str:
        return "null-asset"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.NULL

    @classmethod
    def from_query_class(cls, asset: CNANullAssetV1) -> Asset:
        config = cls.aggregate_config(asset)
        return NullAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            bindings=set(),
            name=asset.identifier,
            addr_block=config.addr_block,
        )
