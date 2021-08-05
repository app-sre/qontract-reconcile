from contextlib import contextmanager

from ldap3 import Server, Connection, ALL, SAFE_SYNC
from reconcile.utils.config import get_config

_base_dn = None


@contextmanager
def init(serverUrl):
    server = Server(serverUrl, get_info=ALL)
    client = Connection(server, None, None, client_strategy=SAFE_SYNC)
    try:
        client.bind()
        yield client
    finally:
        client.unbind()


def init_from_config():
    global _base_dn

    config = get_config()

    serverUrl = config['ldap']['server']
    _base_dn = config['ldap']['base_dn']
    return init(serverUrl)


def users_exist(users):
    global _base_dn

    with init_from_config() as client:
        _, _, results, _ = client.search(_base_dn, '(&(objectclass=person))')
        existing_users = set()
        for r in results:
            dn = r['dn']
            uid = dn.replace(',' + _base_dn, '').replace('uid=', '')
            existing_users.add(uid)
        for u in users:
            u['delete'] = False if u['username'] in existing_users else True
        return users
