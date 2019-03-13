import time
import requests
import hvac
from utils.config import get_config

_client = None


class SecretNotFound(Exception):
    pass


class SecretFieldNotFound(Exception):
    pass


class VaultConnectionError(Exception):
    pass


def init(server, role_id, secret_id):
    global _client

    if _client is None:
        client = hvac.Client(url=server)

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


def read(path, field):
    global _client
    init_from_config()

    secret = _client.read(path)

    if secret is None or 'data' not in secret:
        raise SecretNotFound(path)

    try:
        secret_field = secret['data'][field]
    except KeyError:
        raise SecretFieldNotFound("{}/{}".format(path, field))

    return secret_field


def read_all(path):
    global _client
    init_from_config()

    secret = _client.read(path)

    if secret is None or 'data' not in secret:
        raise SecretNotFound(path)

    return secret['data']


def read_all_v2(path, version):
    global _client
    init_from_config()

    path_split = path.split('/')
    mount_point = path_split[0]
    read_path = '/'.join(path_split[1:])

    secret = _client.secrets.kv.v2.read_secret_version(
        mount_point=mount_point,
        path=read_path,
        version=version,
    )

    if secret is None or 'data' not in secret or 'data' not in secret['data']:
        raise SecretNotFound(path)

    return secret['data']['data']
