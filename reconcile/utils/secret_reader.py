from abc import ABC, abstractmethod
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


class TypedSecretReader(ABC):
    @abstractmethod
    def _read(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        raise NotImplementedError()

    @abstractmethod
    def _read_all(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        raise NotImplementedError()

    def read(self, secret: Mapping[str, Any]) -> dict[str, str]:
        """
        Kept to stay backwards compatible with to-be deprecated
        SecretReader. Once SecretReader is not used, we can
        remove this.
        """
        return self._read(
            path=secret.get("path"),
            field=secret.get("field"),
            format=secret.get("format"),
            version=secret.get("version"),
        )

    def read_all(self, secret: Mapping[str, Any]) -> dict[str, str]:
        """
        Kept to stay backwards compatible with to-be deprecated
        SecretReader. Once SecretReader is not used, we can
        remove this.
        """
        return self._read_all(
            path=secret.get("path"),
            field=secret.get("field"),
            format=secret.get("format"),
            version=secret.get("version"),
        )

    def typed_read(self, secret: SupportsSecret) -> dict[str, str]:
        return self._read(
            path=secret.path,
            field=secret.field,
            format=secret.q_format,
            version=secret.version,
        )

    def typed_read_all(self, secret: SupportsSecret) -> dict[str, str]:
        return self._read_all(
            path=secret.path,
            field=secret.field,
            format=secret.q_format,
            version=secret.version,
        )

    def read_with_parameters(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        return self._read(
            path=path,
            field=field,
            format=format,
            version=version,
        )

    def read_all_with_parameters(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        return self._read_all(
            path=path,
            field=field,
            format=format,
            version=version,
        )

    def _parameters_to_dict(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, Any]:
        return {
            "path": path,
            "field": field,
            "format": format,
            "version": version,
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
    def _read_all(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        try:
            data = self.vault_client.read_all(
                self._parameters_to_dict(
                    path=path,
                    field=field,
                    format=format,
                    version=version,
                )
            )
        except Forbidden:
            raise VaultForbidden(
                f"permission denied reading vault secret " f"at {path}"
            )
        except vault.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data

    @retry()
    def _read(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        try:
            data = self.vault_client.read(
                self._parameters_to_dict(
                    path=path,
                    field=field,
                    format=format,
                    version=version,
                )
            )
        except vault.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data


class ConfigSecretReader(TypedSecretReader):
    """
    Read secrets from a config file
    """

    def _read(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        try:
            data = config.read(
                self._parameters_to_dict(
                    path=path,
                    field=field,
                    format=format,
                    version=version,
                )
            )
        except config.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data

    def _read_all(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        try:
            data = config.read_all(
                self._parameters_to_dict(
                    path=path,
                    field=field,
                    format=format,
                    version=version,
                )
            )
        except config.SecretNotFound as e:
            raise SecretNotFound(*e.args) from e
        return data


def create_secret_reader(use_vault: bool) -> TypedSecretReader:
    """
    This function could be used in an integrations run() function to instantiate a
    TypedSecretReader.
    """
    return VaultSecretReader() if use_vault else ConfigSecretReader()


class SecretReader(TypedSecretReader):
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
    def _read(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ):
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

        params = self._parameters_to_dict(
            path=path,
            field=field,
            format=format,
            version=version,
        )

        if self.settings and self.settings.get("vault"):
            try:
                data = self.vault_client.read(params)
            except vault.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e
        else:
            try:
                data = config.read(params)
            except config.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e

        return data

    @retry()
    def _read_all(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ):
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

        params = self._parameters_to_dict(
            path=path,
            field=field,
            format=format,
            version=version,
        )

        if self.settings and self.settings.get("vault"):
            try:
                data = self.vault_client.read_all(params)
            except Forbidden:
                raise VaultForbidden(
                    f"permission denied reading vault secret " f"at {path}"
                )
            except vault.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e
        else:
            try:
                data = config.read_all(params)
            except config.SecretNotFound as e:
                raise SecretNotFound(*e.args) from e

        return data
