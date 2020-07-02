import time
import requests
import hvac
import base64

from sretoolbox.utils import retry

from reconcile.constants import DEFAULT_THREADS
from utils.config import get_config

_client = None


class SecretNotFound(Exception):
    pass


class SecretVersionNotFound(Exception):
    pass


class SecretFieldNotFound(Exception):
    pass


class VaultConnectionError(Exception):
    pass


def init(server, role_id, secret_id):
    global _client

    if _client is None:
        # This is a threaded world. Let's define a
        # connections pool to live in that world
        # (this avoids the warning "Connection pool is
        # full, discarding connection: vault.devshift.net")
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=DEFAULT_THREADS,
            pool_maxsize=DEFAULT_THREADS
        )
        session.mount('https://', adapter)
        client = hvac.Client(url=server, session=session)

        authenticated = False
        for i in range(0, 3):
            try:
                client.auth_approle(role_id, secret_id)
                authenticated = client.is_authenticated()
                break
            except requests.exceptions.ConnectionError:
                time.sleep(1)

        if not authenticated:
            raise VaultConnectionError()

        _client = client


def init_from_config():
    config = get_config()

    server = config['vault']['server']
    role_id = config['vault']['role_id']
    secret_id = config['vault']['secret_id']

    return init(server, role_id, secret_id)


@retry()
def read(secret):
    """Returns a value of a key in a Vault secret.

    The input secret is a dictionary which contains the following fields:
    * path - path to the secret in Vault
    * field - the key to read from the secret
    * format (optional) - plain or base64 (defaults to plain)
    * version (optional) - secret version to read (if this is a v2 KV engine)
    """
    secret_path = secret['path']
    secret_field = secret['field']
    secret_format = secret.get('format', 'plain')
    secret_version = secret.get('version')

    try:
        data = _read_v2(secret_path, secret_field, secret_version)
    except Exception:
        data = _read_v1(secret_path, secret_field)

    return base64.b64decode(data) if secret_format == 'base64' else data


def write(secret):
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
        _write_v1(secret_path, data)
    except Exception:
        _write_v2(secret_path, data)


@retry()
def read_all(secret):
    """Returns a dictionary of keys and values in a Vault secret.

    The input secret is a dictionary which contains the following fields:
    * path - path to the secret in Vault
    * version (optional) - secret version to read (if this is a v2 KV engine)
    """
    secret_path = secret['path']
    secret_version = secret.get('version')
    try:
        data = _read_all_v2(secret_path, secret_version)
    except Exception:
        data = _read_all_v1(secret_path)

    return data


def _read_v1(path, field):
    data = _read_all_v1(path)
    try:
        secret_field = data[field]
    except KeyError:
        raise SecretFieldNotFound("{}/{}".format(path, field))

    return secret_field


def _write_v1(path, data):
    global _client
    init_from_config()

    _client.write(path, **data)


def _read_all_v1(path):
    global _client
    init_from_config()

    secret = _client.read(path)

    if secret is None or 'data' not in secret:
        raise SecretNotFound(path)

    return secret['data']


def _read_v2(path, field, version):
    data = _read_all_v2(path, version)
    try:
        secret_field = data[field]
    except KeyError:
        raise SecretFieldNotFound("{}/{} ({})".format(path, field, version))

    return secret_field


def _write_v2(path, data):
    raise NotImplementedError('vault_client write v2')


def _read_all_v2(path, version):
    global _client
    init_from_config()

    path_split = path.split('/')
    mount_point = path_split[0]
    read_path = '/'.join(path_split[1:])

    try:
        secret = _client.secrets.kv.v2.read_secret_version(
            mount_point=mount_point,
            path=read_path,
            version=version,
        )
    except hvac.exceptions.InvalidPath:
        msg = 'version \'{}\' not found for secret with path \'{}\'.'.format(
            version,
            path
        )
        raise SecretVersionNotFound(msg)

    if secret is None or 'data' not in secret or 'data' not in secret['data']:
        raise SecretNotFound(path)

    return secret['data']['data']
