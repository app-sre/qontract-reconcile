from ldap3 import Server, Connection, ALL, SAFE_SYNC
from typing import Iterable


class LdapClient:
    """
    LdapClient that wraps search functionality from ldap3 library
    and exposes through its own method. The client should be used
    `with` statement to allow context manager to release connection resource
    appropriately.
    """

    def __init__(self, settings: dict):
        self.base_dn = settings["ldap"]["baseDn"]
        self.server_url = settings["ldap"]["serverUrl"]
        self.connection = Connection(
            Server(self.server_url, get_info=ALL),
            None,
            None,
            client_strategy=SAFE_SYNC,
        )

    def __enter__(self):
        self.connection.bind()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.unbind()

    def get_users(self, uids: Iterable[str]) -> set[str]:
        search_filter = self.apply_search_filter_by_person(uids)
        _, _, results, _ = self.connection.search(
            self.base_dn, search_filter, attributes=["uid"]
        )
        return set(r["attributes"]["uid"][0] for r in results)

    @staticmethod
    def apply_search_filter_by_person(uids: Iterable[str]) -> str:
        user_filter = "".join((f"(uid={u})" for u in uids))
        return f"(&(objectclass=person)(|{user_filter}))"
