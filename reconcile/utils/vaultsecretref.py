from dataclasses import dataclass
from typing import (
    cast,
)

from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)


@dataclass
class VaultSecretRef:
    _ALL_FIELDS = "all"

    path: str
    field: str
    format: str | None = None
    version: int | None = None

    def get(self, field=None, default=None):
        secret_content = self._resolve_secret()
        if field:
            return secret_content.get(field, default)
        if self.field == VaultSecretRef._ALL_FIELDS:
            return secret_content
        return secret_content.get(self.field, default)

    def _resolve_secret(self) -> dict[str, str]:
        vault_client = cast(_VaultClient, VaultClient())
        if self.field == VaultSecretRef._ALL_FIELDS:
            return vault_client.read_all(self.__dict__)
        field_value = vault_client.read(self.__dict__)
        return {self.field: field_value}
