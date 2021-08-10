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


def get_users(uids):
    global _base_dn

    with init_from_config() as client:
        user_filter = "".join((f"(uid={u})" for u in uids))
        _, _, results, _ = client.search(
            _base_dn,
            f'(&(objectclass=person)(|{user_filter}))',
            attributes=["uid"]
        )
        # pylint: disable=not-an-iterable
        return set(r['attributes']['uid'][0] for r in results)
