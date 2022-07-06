from abc import ABC, abstractmethod
from typing import Iterable, Optional

from reconcile.utils.external_resource_spec import ExternalResourceSpec


class TerraformConfigClient(ABC):
    """Early proposal, might decide to change dump() signature."""

    @abstractmethod
    def add_specs(self, specs: Iterable[ExternalResourceSpec]) -> None:
        ...

    @abstractmethod
    def populate_resources(self) -> None:
        ...

    @abstractmethod
    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dir: Optional[str] = None,
    ) -> str:
        ...

    @abstractmethod
    def dumps(self) -> str:
        ...
