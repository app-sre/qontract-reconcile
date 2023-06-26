from dataclasses import dataclass


@dataclass
class IntegrationMeta:
    name: str
    options: list[str]
