from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class AssetError(Exception):
    pass


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

    @abstractmethod
    def update_from(self, asset: Asset) -> Asset:
        raise NotImplementedError()
