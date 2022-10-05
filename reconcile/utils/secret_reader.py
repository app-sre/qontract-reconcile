from typing import Mapping, Optional, Protocol

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


class SecretReader:
    """Read secrets from either Vault or a config file."""

    def __init__(self, settings: Optional[Mapping] = None) -> None:
        """
        :param settings: app-interface-settings object. It is a dictionary
        containing `value: true` if Vault is to be used as the secret backend.
        """
        self.settings = settings
        self._vault_client: Optional[VaultClient] = None

    @property
    def vault_client(self):
        if self._vault_client is None:
            self._vault_client = VaultClient()
        return self._vault_client

    @retry()
    def read(self, secret: Mapping[str, str]):
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

        if self.settings and self.settings.get("vault"):
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
    def read_all(self, secret: Mapping[str, str]):
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

        if self.settings and self.settings.get("vault"):
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
