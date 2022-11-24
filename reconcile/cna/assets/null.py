from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
from collections.abc import Mapping
from pydantic.dataclasses import dataclass
from pydantic import Field

from reconcile.cna.assets.asset import (
    Asset,
    AssetType,
    AssetStatus,
    AssetModelConfig,
)
from reconcile.gql_definitions.cna.queries.cna_resources import (
    CNANullAssetV1,
    CNANullAssetConfigV1,
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
