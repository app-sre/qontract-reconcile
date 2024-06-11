from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reconcile.cna.assets.asset import (
    Asset,
    AssetError,
    AssetStatus,
    AssetType,
)
from reconcile.gql_definitions.cna.queries.cna_resources import CNANullAssetV1


@dataclass(frozen=True)
class NullAsset(Asset):
    addr_block: str | None

    def api_payload(self) -> dict[str, Any]:
        return {
            "asset_type": "null",
            "name": self.name,
            "parameters": {
                "addr_block": self.addr_block,
            },
        }

    def update_from(self, asset: Asset) -> Asset:
        if not isinstance(asset, NullAsset):
            raise AssetError(f"Cannot create NullAsset from {asset}")
        return NullAsset(
            uuid=self.uuid,
            href=self.href,
            status=self.status,
            name=self.name,
            kind=self.kind,
            addr_block=asset.addr_block,
        )

    @staticmethod
    def from_query_class(asset: CNANullAssetV1) -> NullAsset:
        return NullAsset(
            uuid=None,
            href=None,
            status=None,
            kind=AssetType.NULL,
            name=asset.name,
            addr_block=asset.addr_block,
        )

    @staticmethod
    def from_api_mapping(asset: Mapping[str, Any]) -> NullAsset:
        return NullAsset(
            uuid=asset.get("id"),
            href=asset.get("href"),
            status=AssetStatus(asset.get("status")),
            kind=AssetType.NULL,
            name=asset.get("name", ""),
            addr_block=asset.get("addr_block"),
        )
