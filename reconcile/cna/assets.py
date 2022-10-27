from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from reconcile.gql_definitions.cna.queries.cna_resources import CNANullAssetV1


class AssetType(Enum):
    NULL = "null"


class AssetStatus(Enum):
    TERMINATED = "Terminated"
    PENDING = "Pending"
    RUNNING = "Running"


@dataclass
class Asset(ABC):
    uuid: Optional[str]
    href: Optional[str]
    status: Optional[AssetStatus]
    name: str
    kind: AssetType

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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NullAsset):
            return False
        return other.addr_block == self.addr_block and other.name == self.name

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(
            str(self.uuid)
            + str(self.href)
            + self.name
            + str(self.kind)
            + str(self.addr_block)
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
