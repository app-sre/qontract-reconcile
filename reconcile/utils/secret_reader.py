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


class TypedSecretReader:
    def read(self, secret: SupportsSecret) -> dict[str, str]:
        raise NotImplementedError()

    def read_all(self, secret: SupportsSecret) -> dict[str, str]:
        raise NotImplementedError()

    def _secret_to_dict(self, secret: SupportsSecret) -> dict[str, Any]:
        """
        Config.read() and VaultClient.read() do not support types yet.
        Once they do, we can remove this helper function.
        """
        return {
            "path": secret.path,
            "field": secret.field,
            "version": secret.version,
            "format": secret.q_format,
        }


class VaultSecretReader(TypedSecretReader):
    """
    Read secrets from vault via a vault_client
    """

    def __init__(self, vault_client: Optional[VaultClient] = None):
        self._vault_client = vault_client

    @property
    def vault_client(self):
        if self._vault_client is None:
            self._vault_client = VaultClient()
        return self._vault_client

    @retry()
    def read(self, secret: SupportsSecret) -> dict[str, str]:
        try:
            data = self.vault_client.read(self._secret_to_dict(secret))
        except vault.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data

    @retry()
    def read_all(self, secret: SupportsSecret) -> dict[str, str]:
        try:
            data = self.vault_client.read_all(self._secret_to_dict(secret))
        except Forbidden:
            raise VaultForbidden(
                f"permission denied reading vault secret " f"at {secret.path}"
            )
        except vault.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data


class ConfigSecretReader(TypedSecretReader):
    """
    Read secrets from a config file
    """

    def read(self, secret: SupportsSecret) -> dict[str, str]:
        try:
            data = config.read(self._secret_to_dict(secret))
        except config.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data

    def read_all(self, secret: SupportsSecret) -> dict[str, str]:
        try:
            data = config.read_all(self._secret_to_dict(secret))
        except config.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data


def create_secret_reader(
    settings: Optional[SupportsVaultSettings],
) -> TypedSecretReader:
    """
    This function could be used in an integrations run() function to instantiate a
    TypedSecretReader.
    """
    return VaultSecretReader() if settings and settings.vault else ConfigSecretReader()


class SecretReader:
    """
    Read secrets from either Vault or a config file.

    This class is untyped and we try to eliminate it across our codebase.
    Consider using create_secret_reader() instead.
    """

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
