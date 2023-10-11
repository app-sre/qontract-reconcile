import logging
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    Optional,
)

from reconcile.gql_definitions.ldap_groups.roles import RoleV1
from reconcile.gql_definitions.ldap_groups.roles import query as roles_query
from reconcile.gql_definitions.ldap_groups.settings import LdapGroupsSettingsV1
from reconcile.gql_definitions.ldap_groups.settings import query as settings_query
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_iterables
from reconcile.utils.exceptions import (
    AppInterfaceLdapGroupsSettingsError,
    AppInterfaceSettingsError,
)
from reconcile.utils.helpers import find_duplicates
from reconcile.utils.internal_groups.client import (
    InternalGroupsClient,
    NotFound,
)
from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "ldap-groups"


class LdapGroupsIntegrationParams(PydanticRunParams):
    ...


class LdapGroupsIntegration(QontractReconcileIntegration[LdapGroupsIntegrationParams]):
    """Manage LDAP groups based on App-Interface roles."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(self) -> Optional[dict[str, Any]]:
        return {"roles": [c.dict() for c in self.get_roles(gql.get_api().query)]}

    @defer
    def run(self, dry_run: bool, defer: Optional[Callable] = None) -> None:
        gql_api = gql.get_api()
        roles = self.get_roles(gql_api.query)
        if not roles:
            logging.debug("No roles found.")
            return
        self.settings = self.get_integration_settings(gql_api.query)
        secret = self.secret_reader.read_all_secret(self.settings.credentials)

        # APIs
        state_obj = init_state(integration=self.name, secret_reader=self.secret_reader)
        internal_groups_client = InternalGroupsClient(
            secret["api_url"],
            secret["issuer_url"],
            secret["client_id"],
            secret["client_secret"],
        )
        if defer:
            defer(state_obj.cleanup)
            defer(internal_groups_client.close)

        # run
        desired_groups = self.fetch_desired_state(
            roles,
            contact_list=self.settings.contact_list,
            owners=[
                Entity(
                    type=EntityType.SERVICE_ACCOUNT,
                    # OIDC service accounts are named service-account-<client_id>
                    id=f'service-account-{secret["client_id"]}',
                )
            ],
        )

        group_names = self.get_managed_groups(state_obj)
        # take desired groups into account to support overtaking existing ones
        group_names.update(g.name for g in desired_groups)
        current_groups = self.fetch_current_state(
            internal_groups_client, group_names=group_names
        )
        try:
            self.reconcile(
                dry_run=dry_run,
                internal_groups_client=internal_groups_client,
                desired_groups=desired_groups,
                current_groups=current_groups,
            )
        finally:
            self.set_managed_groups(dry_run=dry_run, state_obj=state_obj)

    def get_managed_groups(self, state_obj: State) -> set[str]:
        try:
            return set(state_obj["managed_groups"])
        except KeyError:
            return set()

    def set_managed_groups(self, dry_run: bool, state_obj: State) -> None:
        if not dry_run:
            state_obj["managed_groups"] = sorted(self._managed_groups)

    @staticmethod
    def get_integration_settings(query_func: Callable) -> LdapGroupsSettingsV1:
        data = settings_query(query_func)
        if not data.settings:
            raise AppInterfaceSettingsError("No app-interface settings found.")
        if not data.settings[0].ldap_groups:
            raise AppInterfaceLdapGroupsSettingsError(
                "No app-interface ldap-groups settings found."
            )
        return data.settings[0].ldap_groups

    def get_roles(self, query_func: Callable) -> list[RoleV1]:
        data = roles_query(query_func, variables={})
        roles = [role for role in data.roles or [] if role.ldap_group]
        duplicates = find_duplicates(role.ldap_group for role in roles)
        if duplicates:
            for dup in duplicates:
                logging.error(f"{dup} is already in use by another role.")
            raise ValueError("Duplicate ldapGroup value(s) found.")
        return roles

    def fetch_desired_state(
        self, roles: Iterable[RoleV1], owners: Iterable[Entity], contact_list: str
    ) -> list[Group]:
        return [
            Group(
                name=role.ldap_group,
                description="Persisted App-Interface role. Managed by qontract-reconcile",
                display_name=f"{role.ldap_group} (App-Interface))",
                members=[
                    Entity(type=EntityType.USER, id=user.org_username)
                    for user in role.users
                ],
                # only owners can modify the group (e.g. add/remove members)
                owners=owners,
                contact_list=contact_list,
            )
            for role in roles
            # roles with empty ldap_group are already filtered out in get_roles; just make mypy happy
            if role.ldap_group
        ]

    def fetch_current_state(
        self, internal_groups_client: InternalGroupsClient, group_names: Iterable[str]
    ) -> list[Group]:
        groups = []
        for group_name in group_names:
            try:
                groups.append(internal_groups_client.group(group_name))
            except NotFound:
                pass
        return groups

    def reconcile(
        self,
        dry_run: bool,
        internal_groups_client: InternalGroupsClient,
        desired_groups: Iterable[Group],
        current_groups: Iterable[Group],
    ) -> None:
        diff_result = diff_iterables(
            current_groups,
            desired_groups,
            key=lambda g: g.name,
            equal=lambda g1, g2: g1 == g2,
        )
        # Internal Groups API does not support listing all managed groups, therefore
        # we need to keep track of them ourselves.
        self._managed_groups = {g.name for g in current_groups}

        for group_to_add in diff_result.add.values():
            logging.info(
                [
                    "create_ldap_group",
                    group_to_add.name,
                    f"users={', '.join(u.id for u in group_to_add.members)}",
                ]
            )
            if not dry_run:
                internal_groups_client.create_group(group_to_add)
                self._managed_groups.add(group_to_add.name)

        for group_to_remove in diff_result.delete.values():
            logging.info(["delete_ldap_group", group_to_remove.name])
            if not dry_run:
                try:
                    internal_groups_client.delete_group(group_to_remove.name)
                except NotFound:
                    pass
                self._managed_groups.remove(group_to_remove.name)

        for diff_pair in diff_result.change.values():
            group_to_update = diff_pair.desired
            logging.info(
                [
                    "update_ldap_group",
                    group_to_update.name,
                    f"users={', '.join(u.id for u in group_to_update.members)}",
                ]
            )
            if not dry_run:
                internal_groups_client.update_group(group_to_update)
