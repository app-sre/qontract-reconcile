import dataclasses
from dataclasses import dataclass
from typing import Optional


@dataclass
class IntegrationMeta:
    name: str
    args: list[str]
    short_help: str | None

    def to_dict(self):
        return dataclasses.asdict(self)
