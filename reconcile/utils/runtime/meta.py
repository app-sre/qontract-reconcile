import dataclasses
from dataclasses import dataclass


@dataclass
class IntegrationMeta:
    name: str
    args: list[str]
    short_help: str | None

    def to_dict(self):
        return dataclasses.asdict(self)
