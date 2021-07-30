from ldap3 import Server, Connection, ALL, SAFE_SYNC
from reconcile.utils.config import get_config

_base_dn = None


def init(serverUrl):
    server = Server(serverUrl, get_info=ALL)

    client = Connection(server, None, None, client_strategy=SAFE_SYNC)
    client.bind()

    return client


def init_from_config():
    global _base_dn

    config = get_config()

    serverUrl = config['ldap']['server']
    _base_dn = config['ldap']['base_dn']
    return init(serverUrl)


def user_exists(username):
    global _base_dn

    client = init_from_config()

    if not client.bound:
        client.bind()

    search_filter = "uid={},{}".format(username, _base_dn)
    result, _, _, _ = client.search(search_filter, '(objectclass=person)')

    client.unbind()

    return result
