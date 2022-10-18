from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from reconcile.gql_definitions.cna.queries.cna_resources import CNANullResourceV1


class AssetStatus(Enum):
    TERMINATED = "Terminated"
    PENDING = "Pending"


@dataclass
class Asset(ABC):
    uuid: Optional[str]
    href: Optional[str]
    status: Optional[AssetStatus]
    name: str

    @abstractmethod
    def api_payload(self) -> dict[str, Any]:
        raise NotImplementedError()


@dataclass
class NullAsset(Asset):
    addr_block: Optional[str]

    def api_payload(self) -> dict[str, Any]:
        return {
            "asset_type": "null",
            "name": self.name,
            "parameters": {
                "addr_block": self.addr_block,
            },
        }

    @staticmethod
    def from_query_class(asset: CNANullResourceV1) -> NullAsset:
        return NullAsset(
            uuid=None,
            href=None,
            status=None,
            name=asset.name,
            addr_block=asset.addr_block,
        )

    @staticmethod
    def from_api_mapping(asset: Mapping[str, Any]) -> NullAsset:
        return NullAsset(
            uuid=asset.get("id"),
            href=asset.get("href"),
            status=AssetStatus(asset.get("status")),
            name=asset.get("name", ""),
            addr_block=asset.get("addr_block"),
        )
