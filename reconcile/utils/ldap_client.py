from ldap3 import Server, Connection, ALL, SAFE_SYNC


class LdapClient:
    """
    LdapClient that wraps search functionality from ldap3 library
    and exposes through its own method. The client should be used
    `with` statement to allow context manager to release connection resource
    appropriately.
    """
    def __init__(self, base_dn, connection):
        self.base_dn = base_dn
        self.connection = connection

    def __enter__(self):
        self.connection.bind()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.unbind()

    def get_users(self, uids: list) -> set:
        user_filter = "".join((f"(uid={u})" for u in uids))
        _, _, results, _ = self.connection.search(
            self.base_dn,
            f'(&(objectclass=person)(|{user_filter}))',
            attributes=["uid"]
        )
        return set(r['attributes']['uid'][0] for r in results)

    @staticmethod
    def from_settings(settings):
        connection = Connection(Server(settings['ldap']['serverUrl'], get_info=ALL), None, None,
                                client_strategy=SAFE_SYNC)
        base_dn = settings['ldap']['baseDn']
        return LdapClient(base_dn, connection)

