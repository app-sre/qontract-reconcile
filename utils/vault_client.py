import hvac
from reconcile.config import get_config

_client = None


def init(server, role_id, secret_id):
    global _client

    if _client is None:
        _client = hvac.Client(url=server)

    _client.auth_approle(role_id, secret_id)

    return _client


def init_from_config():
    config = get_config()

    server = config['vault']['server']
    role_id = config['vault']['role_id']
    secret_id = config['vault']['secret_id']

    return init(server, role_id, secret_id)


def read(path, field):
    global _client
    init_from_config()
    return _client.read(path)['data'][field]
