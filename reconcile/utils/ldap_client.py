from collections import defaultdict
from collections.abc import Iterable

from ldap3 import (
    ALL,
    SAFE_SYNC,
    Connection,
    Server,
)


class LdapClient:
    """
    LdapClient that wraps search functionality from ldap3 library
    and exposes through its own method. The client should be used
    `with` statement to allow context manager to release connection resource
    appropriately.
    """

    def __init__(self, base_dn: str, connection: Connection):
        self.base_dn = base_dn
        self.connection = connection

    def __enter__(self):
        self.connection.bind()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.unbind()

    def get_users(self, uids: Iterable[str]) -> set[str]:
        user_filter = "".join(f"(uid={u})" for u in uids)
        _, _, results, _ = self.connection.search(
            self.base_dn, f"(&(objectclass=person)(|{user_filter}))", attributes=["uid"]
        )
        return {r["attributes"]["uid"][0] for r in results}

    def get_group_members(self, groups_dns: set[str]) -> dict[str, set[str]]:
        """
        Returns a dictionary of group dns and their members.
        """
        if not groups_dns:
            return {}
        filter = f"(|{''.join([f'(memberOf={dn})' for dn in sorted(groups_dns)])})"

        _, _, users, _ = self.connection.search(
            self.base_dn,
            filter,
            attributes=["uid", "memberOf"],
        )
        groups_and_members: dict[str, set[str]] = defaultdict(set[str])
        for u in users:
            uid = u["attributes"]["uid"][0]
            for group in set(u["attributes"]["memberOf"]).intersection(groups_dns):
                groups_and_members[group].add(uid)

        return dict(groups_and_members)

    @classmethod
    def from_params(
        cls, server_url: str, user: str | None, password: str | None, base_dn: str
    ) -> "LdapClient":
        connection = Connection(
            Server(server_url, get_info=ALL),
            user,
            password,
            client_strategy=SAFE_SYNC,
        )
        return cls(base_dn, connection)
