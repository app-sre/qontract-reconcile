import dataclasses
from dataclasses import dataclass
from typing import Any


@dataclass
class IntegrationMeta:
    name: str
    args: list[str]
    short_help: str | None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
