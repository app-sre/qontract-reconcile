import time
import requests
import hvac
import base64
import logging

from hvac.exceptions import InvalidPath
from requests.adapters import HTTPAdapter

from sretoolbox.utils import retry

from utils.config import get_config


class SecretNotFound(Exception):
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
    def __init__(self):
        config = get_config()

        server = config['vault']['server']
        role_id = config['vault']['role_id']
        secret_id = config['vault']['secret_id']

        # This is a threaded world. Let's define a big
        # connections pool to live in that world
        # (this avoids the warning "Connection pool is
        # full, discarding connection: vault.devshift.net")
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=100,
                              pool_maxsize=100)
        session.mount('https://', adapter)
        self._client = hvac.Client(url=server, session=session)
        self._cache = {}

        authenticated = False
        for i in range(0, 3):
            try:
                self._client.auth_approle(role_id, secret_id)
                authenticated = self._client.is_authenticated()
                break
            except requests.exceptions.ConnectionError:
                time.sleep(1)

        if not authenticated:
            raise VaultConnectionError()

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
        try:
            data = self._read_all_v2(secret_path, secret_version)
        except Exception:
            data = self._read_all_v1(secret_path)
        return data

    def _read_all_v2(self, path, version):
        cache_key = (path, version)
        cache_value = self._cache.get(cache_key)
        if cache_value is not None:
            logging.debug('Vault v2 cache hit')
            return cache_value

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
        if secret is None or 'data' not in secret \
                or 'data' not in secret['data']:
            raise SecretNotFound(path)

        data = secret['data']['data']
        self._cache[cache_key] = data
        return data

    def _read_all_v1(self, path):
        secret = self._client.read(path)
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
        try:
            data = self._read_v2(secret_path, secret_field, secret_version)
        except Exception:
            data = self._read_v1(secret_path, secret_field)
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

        try:
            self._write_v1(secret_path, data)
        except Exception:
            self._write_v2(secret_path, data)

    def _write_v2(self, path, data):
        raise NotImplementedError('vault_client write v2')

    def _write_v1(self, path, data):
        self._client.write(path, **data)


class VaultClient:

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = _VaultClient(*args, **kwargs)
            return cls._instance

        if not cls._instance._client.is_authenticated():
            cls._instance = _VaultClient(*args, **kwargs)
            return cls._instance

        return cls._instance
