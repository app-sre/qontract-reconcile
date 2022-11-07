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
    CNAssetV1,
)


@dataclass(frozen=True, config=AssetModelConfig)
class NullAsset(Asset):
    addr_block: Optional[str] = Field(None, alias="AddrBlock")

    @staticmethod
    def provider() -> str:
        return "null-asset"

    @staticmethod
    def asset_type() -> AssetType:
        return AssetType.NULL

    @staticmethod
    def from_query_class(asset: CNAssetV1) -> Asset:
        assert isinstance(asset, CNANullAssetV1)
        return NullAsset(
            id=None,
            href=None,
            status=AssetStatus.UNKNOWN,
            name=asset.name,
            addr_block=asset.addr_block,
        )
