from ldap3 import Server, Connection, ALL
from utils.config import get_config

_client = None
_base_dn = None


def init(serverUrl):
    global _client

    if _client is None:
        server = Server(serverUrl, get_info=ALL)
        _client = Connection(server, None, None, auto_bind=True)

    return _client


def init_from_config():
    global _base_dn

    config = get_config()

    serverUrl = config['ldap']['server']
    _base_dn = config['ldap']['base_dn']

    return init(serverUrl)


def user_exists(username):
    global _client
    global _base_dn

    init_from_config()

    search_filter = "uid={},{}".format(username, _base_dn)

    return _client.search(search_filter, '(objectclass=person)')
