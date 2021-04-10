import os
import base64
import time
import functools
import threading
import logging

import hvac
import requests

from hvac.exceptions import InvalidPath
from requests.adapters import HTTPAdapter
from sretoolbox.utils import retry

from reconcile.utils.config import get_config

LOG = logging.getLogger(__name__)
VAULT_AUTO_REFRESH_INTERVAL = int(
    os.getenv('VAULT_AUTO_REFRESH_INTERVAL') or 600)


class SecretNotFound(Exception):
    pass


class SecretAccessForbidden(Exception):
    pass


class SecretVersionNotFound(Exception):
    pass


class SecretFieldNotFound(Exception):
    pass


class VaultConnectionError(Exception):
    pass


class _VaultClient:
    """
    A class representing a Vault client. Allows read/write operations.
    The client caches read requests in-memory if the request is made
    to a versioned KV engine (v2), since that includes both a path
    and a version (no invalidation required).
    """

    def __init__(self, auto_refresh=True):
        config = get_config()

        server = config['vault']['server']
        self.role_id = config['vault']['role_id']
        self.secret_id = config['vault']['secret_id']

        # This is a threaded world. Let's define a big
        # connections pool to live in that world
        # (this avoids the warning "Connection pool is
        # full, discarding connection: vault.devshift.net")
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=100,
                              pool_maxsize=100)
        session.mount('https://', adapter)
        self._client = hvac.Client(url=server, session=session)

        authenticated = False
        for i in range(0, 3):
            try:
                self._refresh_client_auth()
                authenticated = self._client.is_authenticated()
                break
            except requests.exceptions.ConnectionError:
                time.sleep(1)

        if not authenticated:
            raise VaultConnectionError()

        if auto_refresh:
            t = threading.Thread(target=self._auto_refresh_client_auth,
                                 daemon=True)
            t.start()

    def _auto_refresh_client_auth(self):
        """
        Thread that periodically refreshes the vault token
        """
        while True:
            time.sleep(VAULT_AUTO_REFRESH_INTERVAL)
            LOG.debug('auto refresh client auth')
            self._refresh_client_auth()

    def _refresh_client_auth(self):
        self._client.auth_approle(self.role_id, self.secret_id)

    @retry()
    def read_all(self, secret):
        """Returns a dictionary of keys and values in a Vault secret.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault
        * version (optional) - secret version to read (if this is
                               a v2 KV engine)
        """
        secret_path = secret['path']
        secret_version = secret.get('version')

        kv_version = self._get_mount_version_by_secret_path(secret_path)

        data = None
        if kv_version == 2:
            data = self._read_all_v2(secret_path, secret_version)
        else:
            data = self._read_all_v1(secret_path)

        if data is None:
            raise SecretNotFound

        return data

    def _get_mount_version_by_secret_path(self, path):
        path_split = path.split('/')
        mount_point = path_split[0]
        return self._get_mount_version(mount_point)

    @functools.lru_cache()
    def _get_mount_version(self, mount_point):
        try:
            self._client.secrets.kv.v2.read_configuration(mount_point)
            version = 2
        except Exception:
            version = 1

        return version

    @functools.lru_cache(maxsize=None)
    def _read_all_v2(self, path, version):
        path_split = path.split('/')
        mount_point = path_split[0]
        read_path = '/'.join(path_split[1:])
        try:
            secret = self._client.secrets.kv.v2.read_secret_version(
                mount_point=mount_point,
                path=read_path,
                version=version,
            )
        except InvalidPath:
            msg = (f'version \'{version}\' not found '
                   f'for secret with path \'{path}\'.')
            raise SecretVersionNotFound(msg)
        except hvac.exceptions.Forbidden:
            msg = f"permission denied accessing secret '{path}'"
            raise SecretAccessForbidden(msg)
        if secret is None or 'data' not in secret \
                or 'data' not in secret['data']:
            raise SecretNotFound(path)

        data = secret['data']['data']
        return data

    def _read_all_v1(self, path):
        try:
            secret = self._client.read(path)
        except hvac.exceptions.Forbidden:
            msg = f"permission denied accessing secret '{path}'"
            raise SecretAccessForbidden(msg)

        if secret is None or 'data' not in secret:
            raise SecretNotFound(path)

        return secret['data']

    @retry()
    def read(self, secret):
        """Returns a value of a key in a Vault secret.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault
        * field - the key to read from the secret
        * format (optional) - plain or base64 (defaults to plain)
        * version (optional) - secret version to read (if this is
                               a v2 KV engine)
        """
        secret_path = secret['path']
        secret_field = secret['field']
        secret_format = secret.get('format', 'plain')
        secret_version = secret.get('version')

        kv_version = self._get_mount_version_by_secret_path(secret_path)

        data = None
        if kv_version == 2:
            data = self._read_v2(secret_path, secret_field, secret_version)
        else:
            data = self._read_v1(secret_path, secret_field)

        if data is None:
            raise SecretNotFound

        return base64.b64decode(data) if secret_format == 'base64' else data

    def _read_v2(self, path, field, version):
        data = self._read_all_v2(path, version)
        try:
            secret_field = data[field]
        except KeyError:
            raise SecretFieldNotFound(f'{path}/{field} ({version})')
        return secret_field

    def _read_v1(self, path, field):
        data = self._read_all_v1(path)
        try:
            secret_field = data[field]
        except KeyError:
            raise SecretFieldNotFound("{}/{}".format(path, field))
        return secret_field

    @retry()
    def write(self, secret):
        """Writes a dictionary of keys and values to a Vault secret.

        The input secret is a dictionary which contains the following fields:
        * path - path to the secret in Vault
        * data - data (dictionary) to write
        """
        secret_path = secret['path']
        b64_data = secret['data']
        data = {k: base64.b64decode(v or '').decode('utf-8')
                for k, v in b64_data.items()}

        kv_version = self._get_mount_version_by_secret_path(secret_path)
        if kv_version == 2:
            self._write_v2(secret_path, data)
        else:
            self._write_v1(secret_path, data)

    def _write_v2(self, path, data):
        # do not forget to run `self._read_all_v2.cache_clear()`
        # if this ever get's implemented
        raise NotImplementedError('vault_client write v2')

    def _write_v1(self, path, data):
        try:
            self._client.write(path, **data)
        except hvac.exceptions.Forbidden:
            msg = f"permission denied accessing secret '{path}'"
            raise SecretAccessForbidden(msg)


class VaultClient:

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = _VaultClient(*args, **kwargs)
            return cls._instance

        try:
            is_authenticated = cls._instance._client.is_authenticated()
        except requests.exceptions.ConnectionError:
            is_authenticated = False

        if not is_authenticated:
            cls._instance = _VaultClient(*args, **kwargs)
            return cls._instance

        return cls._instance
