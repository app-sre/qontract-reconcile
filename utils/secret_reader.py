from hvac.exceptions import Forbidden
from sretoolbox.utils import retry

import utils.config as config
from utils.vault import VaultClient


class VaultForbidden(Exception):
    pass


class SecretReader:
    def __init__(self, settings=None):
        self.settings = settings
        self._vault_client = None

    @property
    def vault_client(self):
        if self._vault_client is None:
            self._vault_client = VaultClient()
        return self._vault_client

    @retry()
    def read(self, secret):
        """Returns a value of a key from Vault secret or configuration file.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault or config
        * field - the key to read from the secret
        * format (optional) - plain or base64 (defaults to plain)
        * version (optional) - Vault secret version to read
          * Note: if this is Vault secret and a v2 KV engine

        The input settings is an optional app-interface-settings object
        queried from app-interface. It is a dictionary containing `value: true`
        if Vault is to be used as the secret backend.

        Default vault setting is false, to allow using a config file
        without creating app-interface-settings.
        """

        if self.settings and self.settings.get('vault'):
            return self.vault_client.read(secret)
        else:
            return config.read(secret)

    @retry()
    def read_all(self, secret):
        """Returns a dictionary of keys and values
        from Vault secret or configuration file.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault or config
        * version (optional) - Vault secret version to read
          * Note: if this is Vault secret and a v2 KV engine

        The input settings is an optional app-interface-settings object
        queried from app-interface. It is a dictionary containing `value: true`
        if Vault is to be used as the secret backend.

        Default vault setting is false, to allow using a config file
        without creating app-interface-settings.
        """

        if self.settings and self.settings.get('vault'):
            try:
                data = self.vault_client.read_all(secret)
            except Forbidden:
                raise VaultForbidden(f'permission denied reading vault secret '
                                     f'at {secret["path"]}')
            return data
        else:
            return config.read_all(secret)
