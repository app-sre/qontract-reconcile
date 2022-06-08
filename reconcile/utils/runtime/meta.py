from dataclasses import dataclass
import dataclasses
from typing import Optional


@dataclass
class IntegrationMeta:

    name: str
    args: list[str]
    short_help: Optional[str]

    def to_dict(self):
        return dataclasses.asdict(self)
