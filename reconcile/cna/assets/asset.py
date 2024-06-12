from __future__ import annotations

from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import Any


class AssetError(Exception):
    pass


class AssetType(Enum):
    NULL = "null"


class AssetStatus(Enum):
    TERMINATED = "Terminated"
    PENDING = "Pending"
    RUNNING = "Running"


@dataclass(frozen=True)
class Asset(ABC):
    uuid: str | None = field(compare=False, hash=True)
    href: str | None = field(compare=False, hash=True)
    status: AssetStatus | None = field(compare=False, hash=True)
    name: str
    kind: AssetType

    @abstractmethod
    def api_payload(self) -> dict[str, Any]:
        raise NotImplementedError()

    @abstractmethod
    def update_from(self, asset: Asset) -> Asset:
        raise NotImplementedError()
