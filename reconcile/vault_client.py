import hvac
from reconcile.config import get_config

_client = None


def get_client():
    global _client
    return _client


def init(server, token):
    global _client
    _client = hvac.Client(url=server)
    _client.auth.github.login(token=token)
    return _client


def init_from_config():
    config = get_config()

    server = config['vault']['server']
    token = config['vault']['token']

    return init(server, token)


def read(path, field):
    global _client
    return _client.read(path)['data'][field]
