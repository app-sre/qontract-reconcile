from typing import Any, Mapping, Optional, Protocol

from hvac.exceptions import Forbidden
from sretoolbox.utils import retry

from reconcile.utils import config, vault
from reconcile.utils.vault import VaultClient


class VaultForbidden(Exception):
    pass


class SecretNotFound(Exception):
    pass


class SupportsSecret(Protocol):
    """SupportsSecret defines all attributes needed to fetch a secret from Vault or config.

    This is the protocol/interface for app-interface's VaultSecretV1.
    """

    path: str
    field: str
    version: Optional[int]
    q_format: Optional[str]


class SupportsVaultSettings(Protocol):
    """
    SupportsVaultSettings defines all attributes needed from app-interface-settings
    to instantiate a SecretReader
    """

    vault: bool


class SecretReaderBase:
    """Read secrets from either Vault or a config file."""

    def __init__(self, vault_client: Optional[VaultClient] = None) -> None:
        self._vault_client: Optional[VaultClient] = vault_client

    @property
    def vault_client(self):
        if self._vault_client is None:
            self._vault_client = VaultClient()
        return self._vault_client

    @retry()
    def _read_base(self, secret: Mapping[str, Any], use_vault: bool) -> dict[str, str]:
        """Returns a value of a key from Vault secret or configuration file.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault or config
        * field - the key to read from the secret
        * format (optional) - plain or base64 (defaults to plain)
        * version (optional) - Vault secret version to read
          * Note: if this is Vault secret and a v2 KV engine

        Default vault setting is false, to allow using a config file
        without creating app-interface-settings.

        :raises secret_reader.SecretNotFound:
        """

        if use_vault:
            try:
                data = self.vault_client.read(secret)
            except vault.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e
        else:
            try:
                data = config.read(secret)
            except config.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e

        return data

    @retry()
    def _read_all_base(
        self, secret: Mapping[str, Any], use_vault: bool
    ) -> dict[str, str]:
        """Returns a dictionary of keys and values
        from Vault secret or configuration file.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault or config
        * version (optional) - Vault secret version to read
          * Note: if this is Vault secret and a v2 KV engine

        Default vault setting is false, to allow using a config file
        without creating app-interface-settings.

        :raises secret_reader.SecretNotFound:
        """

        if use_vault:
            try:
                data = self.vault_client.read_all(secret)
            except Forbidden:
                raise VaultForbidden(
                    f"permission denied reading vault secret " f'at {secret["path"]}'
                )
            except vault.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e
        else:
            try:
                data = config.read_all(secret)
            except config.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e

        return data


class TypedSecretReader(SecretReaderBase):
    """
    Typed version of SecretReader. Once all references to the
    untyped version are removed, we can merge this fully with
    the SecretReaderBase class.
    """

    def __init__(
        self,
        settings: Optional[SupportsVaultSettings],
        vault_client: Optional[VaultClient] = None,
    ):
        super().__init__(vault_client=vault_client)
        self._use_vault = settings and settings.vault

    def _to_secret_dict(self, secret: SupportsSecret) -> dict[str, Any]:
        """
        VaultClient currently works with dictionaries. Once we got a typed
        version of VaultClient, we could remove this
        """
        return {
            "path": secret.path,
            "field": secret.field,
            "version": secret.version,
            "format": secret.q_format,
        }

    def read(self, secret: SupportsSecret) -> dict[str, str]:
        return self._read_base(
            secret=self._to_secret_dict(secret),
            use_vault=self._use_vault,
        )

    def read_all(self, secret: SupportsSecret) -> dict[str, str]:
        return self._read_all_base(
            secret=self._to_secret_dict(secret),
            use_vault=self._use_vault,
        )


class SecretReader(SecretReaderBase):
    """
    Untyped version of SecretReader.
    Once all references are cleared, this can be removed
    """

    def __init__(self, settings: Optional[Mapping] = None) -> None:
        super().__init__()
        self.settings = settings

    def read(self, secret: Mapping[str, Any]):
        return self._read_base(
            secret=secret,
            use_vault=self.settings and self.settings.get("vault"),
        )

    def read_all(self, secret: Mapping[str, Any]):
        return self._read_all_base(
            secret=secret,
            use_vault=self.settings and self.settings.get("vault"),
        )
