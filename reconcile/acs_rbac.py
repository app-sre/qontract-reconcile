import logging
from collections import defaultdict
from collections.abc import Callable
from typing import (
    Optional,
    Self,
)

from pydantic import BaseModel

from reconcile.gql_definitions.acs.acs_instances import AcsInstanceV1
from reconcile.gql_definitions.acs.acs_instances import query as acs_instances_query
from reconcile.gql_definitions.acs.acs_rbac import OidcPermissionAcsV1
from reconcile.gql_definitions.acs.acs_rbac import query as acs_rbac_query
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.acs_api import (
    AcsApi,
    Group,
)
from reconcile.utils.differ import (
    DiffPair,
    diff_iterables,
)
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

DEFAULT_ADMIN_SCOPE_NAME = "Unrestricted"
DEFAULT_ADMIN_SCOPE_DESC = "Access to all clusters and namespaces"
# map enum values defined in oidc-permission schema to system default ACS values
PERMISSION_SET_NAMES = {
    "admin": "Admin",
    "analyst": "Analyst",
    "vuln-admin": "Vulnerability Management Admin",
}


class AssignmentPair(BaseModel):
    key: str
    value: str


RoleAssignments = dict[str, list[AssignmentPair]]


class AcsAccessScope(BaseModel):
    name: str
    description: str
    clusters: list[str]
    namespaces: list[dict[str, str]]


class Permission(OidcPermissionAcsV1):
    def __hash__(self) -> int:
        return hash(self.name)


class AcsRole(BaseModel):
    """
    AcsRole is derived from oidc-permission-v1
    Due to A-I role-1 ability to reference multiple oidc-permissions
    the A-I role names cannot be used for the roles defined within ACS
    """

    name: str
    description: str
    assignments: list[AssignmentPair]
    permission_set_name: str
    access_scope: AcsAccessScope
    system_default: Optional[bool]

    @classmethod
    def build(cls, permission: Permission, usernames: list[str]) -> Self:
        assignments = [
            AssignmentPair(
                # acs_user attribute from https://github.com/app-sre/qontract-schemas/blob/main/schemas/access/user-1.yml
                # is mapped to email key in auth rules.
                # this is due to current limitation with ACS ability to enforce custom keys in rules
                # see step 5: https://docs.openshift.com/acs/4.2/operating/manage-user-access/manage-role-based-access-control-3630.html#assign-role-to-user-or-group_manage-role-based-access-control
                key="email",
                value=u,
            )
            for u in usernames
        ]

        is_unrestricted_scope = not permission.clusters and not permission.namespaces

        return cls(
            name=permission.name,
            description=permission.description,
            assignments=assignments,
            permission_set_name=PERMISSION_SET_NAMES[permission.permission_set],
            access_scope=AcsAccessScope(
                # Due to api restriction, additional Unrestricted scopes
                # cannot be made.
                # Therefore, desired scopes that meet unrestricted condition
                # are treated as the system default 'Unrestricted'
                name=DEFAULT_ADMIN_SCOPE_NAME
                if is_unrestricted_scope
                else permission.name,
                description=DEFAULT_ADMIN_SCOPE_DESC
                if is_unrestricted_scope
                else permission.description,
                # second arg is returned even if first arg == False
                clusters=[cluster.name for cluster in (permission.clusters or [])],
                # mirroring format of 'rules.includedNamespaces' in /v1/simpleaccessscopes response
                namespaces=[
                    {
                        "clusterName": n.cluster.name,
                        "namespaceName": n.name,
                    }
                    for n in (permission.namespaces or [])
                ],
            ),
            system_default=False,
        )

    def diff_role(self, b: Self) -> bool:
        return (
            self.permission_set_name != b.permission_set_name
            or self.access_scope != b.access_scope
            or self.description != b.description
        )

    def is_unrestricted_scope(self) -> bool:
        # empty cluster and namespaces attributes signifies unrestricted scope
        return not self.access_scope.clusters and not self.access_scope.namespaces


class AcsRbacIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "acs_rbac"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    def get_acs_instance(self, query_func: Callable) -> AcsInstanceV1:
        """
        Get an ACS instance

        :param query_func: function which queries GQL Server
        """
        if instances := acs_instances_query(query_func=query_func).instances:
            # mirroring logic for gitlab instances
            # current assumption is for appsre to only utilize one instance
            if len(instances) != 1:
                raise AppInterfaceSettingsError("More than one ACS instance found!")
            return instances[0]
        raise AppInterfaceSettingsError("No ACS instance found!")

    def get_desired_state(self, query_func: Callable) -> list[AcsRole]:
        """
        Get desired ACS roles and associated users from App Interface

        :param query_func: function which queries GQL server
        :return: list of AcsRole derived from oidc-permission-1 definitions
        """

        query_results = acs_rbac_query(query_func=query_func).acs_rbacs
        if query_results is None:
            return []

        permission_usernames: dict[Permission, list[str]] = defaultdict(list)
        for user in query_results:
            if user.acs_user:  # user file must set acs_user attribute
                for role in user.roles or []:
                    for permission in role.oidc_permissions or []:
                        if isinstance(permission, OidcPermissionAcsV1):
                            permission_usernames[
                                Permission(**permission.dict(by_alias=True))
                            ].append(user.acs_user)
        return [
            AcsRole.build(permission, usernames)
            for permission, usernames in permission_usernames.items()
        ]

    def get_current_state(self, acs: AcsApi, auth_provider_id: str) -> list[AcsRole]:
        """
        Get current ACS roles and associated users from ACS api

        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :return: list of current AcsRole associated with specified auth provider
        """
        current_roles: list[AcsRole] = []

        roles = acs.get_roles()
        groups = acs.get_groups()
        role_assignments: RoleAssignments = self.build_role_assignments(
            auth_provider_id, groups
        )

        for role in roles:
            # process roles that are not system default
            # OR
            # system default roles referenced in auth rules
            # however, do not reconcile the auth provider minimum access rule associated with 'None' system default
            if not role.system_default or (
                role.name in role_assignments and role.name != "None"
            ):
                try:
                    access_scope = acs.get_access_scope_by_id(role.access_scope_id)
                except Exception as e:
                    logging.error(
                        "Failed to retrieve current access scope: %s for role: %s\n\t%s",
                        role.access_scope_id,
                        role.name,
                        e,
                    )
                    continue

                try:
                    permission_set = acs.get_permission_set_by_id(
                        role.permission_set_id
                    )
                except Exception as e:
                    logging.error(
                        "Failed to retrieve current permission set: %s for role: %s\n\t%s",
                        role.permission_set_id,
                        role.name,
                        e,
                    )
                    continue

                current_roles.append(
                    AcsRole(
                        name=role.name,
                        description=role.description,
                        assignments=role_assignments.get(role.name, []),
                        permission_set_name=permission_set.name,
                        system_default=role.system_default,
                        access_scope=AcsAccessScope(
                            name=access_scope.name,
                            description=access_scope.description,
                            clusters=access_scope.clusters,
                            namespaces=access_scope.namespaces,
                        ),
                    )
                )

        return current_roles

    def build_role_assignments(
        self, auth_id: str, groups: list[Group]
    ) -> RoleAssignments:
        """
        Processes Groups returned by ACS api and maps roles to users
        A "group" in ACS api is a rule that assigns a user to a role

        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param groups: list of current Group objects received from api
        :return: dict in which keys are role names and values are list of
                user attributes assigned to role
        """
        auth_rules: RoleAssignments = defaultdict(list)
        for group in groups:
            # part of auth provider specified in A-I to reconcile (internal SSO)
            if group.auth_provider_id == auth_id:
                auth_rules[group.role_name].append(
                    AssignmentPair(key=group.key, value=group.value)
                )
        return auth_rules

    def add_rbac(
        self, to_add: dict[str, AcsRole], acs: AcsApi, auth_id: str, dry_run: bool
    ) -> None:
        """
        Creates desired ACS roles as well as associated access scopes and rules

        :param to_add: result of 'diff_iterables(current, desired).add' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in acs.get_access_scopes()}
        permission_sets_id_map = {ps.name: ps.id for ps in acs.get_permission_sets()}

        for role in to_add.values():
            # skip access scope creation and use existing system default 'Unrestricted' access scope if unrestricted
            # note: this serves to reduce redundant admin scopes but also due to restriction within api when
            # attempting to provision another admin access scope
            if not role.is_unrestricted_scope():
                # recall that a desired role and access scope are derived from a single oidc-permission-1
                # therefore, items in diff.add require creation of dependency access scope first and then role
                if not dry_run:
                    try:
                        as_id = acs.create_access_scope(
                            role.access_scope.name,
                            role.access_scope.description,
                            role.access_scope.clusters,
                            role.access_scope.namespaces,
                        )
                    except Exception as e:
                        logging.error(
                            "Failed to create access scope: %s for role: %s\n\t%s",
                            role.access_scope.name,
                            role.name,
                            e,
                        )
                        continue
                logging.info("Created access scope: %s", role.access_scope.name)

            if not dry_run:
                try:
                    acs.create_role(
                        role.name,
                        role.description,
                        permission_sets_id_map[role.permission_set_name],
                        access_scope_id_map[DEFAULT_ADMIN_SCOPE_NAME]
                        if role.is_unrestricted_scope()
                        else as_id,
                    )
                except Exception as e:
                    logging.error("Failed to create role: %s\n\t%s", role.name, e)
                    continue
            logging.info("Created role: %s", role.name)

            if not dry_run:
                additions = [
                    AcsApi.GroupAdd(
                        role_name=role.name,
                        key=a.key,
                        value=a.value,
                        auth_provider_id=auth_id,
                    )
                    for a in role.assignments
                ]
                try:
                    acs.create_group_batch(additions)
                except Exception as e:
                    logging.error(
                        "Failed to create group(s) for role: %s\n\t%s", role.name, e
                    )
                    continue
            logging.info(
                "Added users to role %s: %s",
                role.name,
                [a.value for a in role.assignments],
            )

    def delete_rbac(
        self, to_delete: dict[str, AcsRole], acs: AcsApi, auth_id: str, dry_run: bool
    ) -> None:
        """
        Deletes desired ACS roles as well as associated access scopes and rules

        :param to_delete: result of 'diff_iterables(current, desired).delete' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in acs.get_access_scopes()}
        role_group_mappings: dict[str, list[Group]] = defaultdict(list)
        for group in acs.get_groups():
            if group.auth_provider_id == auth_id:
                role_group_mappings[group.role_name].append(group)

        # role and associated resources must be deleted in the proceeding order
        for role in to_delete.values():
            if not dry_run:
                try:
                    acs.delete_group_batch(role_group_mappings[role.name])
                except Exception as e:
                    logging.error(
                        "Failed to delete group(s) for role: %s\n\t%s", role.name, e
                    )
                    continue
            logging.info(
                "Deleted users from role %s: %s",
                role.name,
                [a.value for a in role.assignments],
            )
            # only delete rules associated with a system default roles
            # do not continue to deletion of the role and associated access scope
            if role.system_default:
                continue
            if not dry_run:
                try:
                    acs.delete_role(role.name)
                except Exception as e:
                    logging.error("Failed to delete role: %s\n\t%s", role.name, e)
                    continue
            logging.info("Deleted role: %s", role.name)
            if not dry_run:
                try:
                    acs.delete_access_scope(access_scope_id_map[role.access_scope.name])
                except Exception as e:
                    logging.error(
                        "Failed to delete access scope for role: %s\n\t%s", role.name, e
                    )
                    continue
            logging.info("Deleted access scope: %s", role.access_scope.name)

    def update_rbac(
        self,
        to_update: dict[str, DiffPair[AcsRole, AcsRole]],
        acs: AcsApi,
        auth_id: str,
        dry_run: bool,
    ) -> None:
        """
        Updates desired ACS roles as well as associated access scopes and rules

        :param to_update: result of 'diff_iterables(current, desired).change' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in acs.get_access_scopes()}
        permission_sets_id_map = {ps.name: ps.id for ps in acs.get_permission_sets()}
        role_group_mappings: dict[str, dict[str, Group]] = {}
        for group in acs.get_groups():
            if group.role_name not in role_group_mappings:
                role_group_mappings[group.role_name] = {}
            role_group_mappings[group.role_name][group.value] = group

        for role_diff_pair in to_update.values():
            # auth rule (groups) portion
            diff = diff_iterables(
                role_diff_pair.current.assignments,
                role_diff_pair.desired.assignments,
                lambda x: x.value,
            )
            # due to usage of 'value' in auth rules for the key, if a single rule requires a change
            # it will appear as one entry to delete and one entry to add
            # ex: desired value = foo. current value = bar
            # output will be an entry to delete bar and an entry to add foo
            if any((diff.add, diff.delete)):
                old = [
                    role_group_mappings[role_diff_pair.current.name][d.value]
                    for d in diff.delete.values()
                ]
                new = [
                    AcsApi.GroupAdd(
                        role_name=role_diff_pair.desired.name,
                        key=a.key,
                        value=a.value,
                        auth_provider_id=auth_id,
                    )
                    for a in diff.add.values()
                ]
                if not dry_run:
                    try:
                        acs.update_group_batch(old, new)
                    except Exception as e:
                        logging.error(
                            "Failed to update rules for role: %s\n\t%s",
                            role_diff_pair.desired.name,
                            e,
                        )
                        continue
                logging.info(
                    "Updated rules for role '%s':\n"
                    + "\tAdded: %s\n"
                    + "\tDeleted: %s",
                    role_diff_pair.desired.name,
                    [n.value for n in new],
                    [o.value for o in old],
                )

            # access scope portion
            if (
                role_diff_pair.current.access_scope
                != role_diff_pair.desired.access_scope
            ):
                if not dry_run:
                    try:
                        acs.update_access_scope(
                            access_scope_id_map[
                                role_diff_pair.desired.access_scope.name
                            ],
                            role_diff_pair.desired.access_scope.name,
                            role_diff_pair.desired.access_scope.description,
                            role_diff_pair.desired.access_scope.clusters,
                            role_diff_pair.desired.access_scope.namespaces,
                        )
                    except Exception as e:
                        logging.error(
                            "Failed to update access scope: %s\n\t%s",
                            role_diff_pair.desired.access_scope.name,
                            e,
                        )
                        continue
                logging.info(
                    "Updated access scope %s", role_diff_pair.desired.access_scope.name
                )

            # role portion
            # access scope is included in diff check once more here
            # in case the role needs to be assigned different access scope.
            # changes to access scope resource are handled in dedicated section above
            # assignments are not included in this diff. Handled in dedicated section above
            if role_diff_pair.current.diff_role(role_diff_pair.desired):
                if not dry_run:
                    try:
                        acs.update_role(
                            role_diff_pair.desired.name,
                            role_diff_pair.desired.description,
                            permission_sets_id_map[
                                role_diff_pair.desired.permission_set_name
                            ],
                            access_scope_id_map[
                                role_diff_pair.desired.access_scope.name
                            ],
                        )
                    except Exception as e:
                        logging.error(
                            "Failed to update role: %s\n\t%s",
                            role_diff_pair.desired.name,
                            e,
                        )
                        continue
                logging.info("Updated role: %s", role_diff_pair.desired.name)

    def reconcile(
        self,
        desired: list[AcsRole],
        current: list[AcsRole],
        acs: AcsApi,
        auth_provider_id: str,
        dry_run: bool,
    ) -> None:
        diff = diff_iterables(current, desired, lambda x: x.name)
        if len(diff.add) > 0:
            self.add_rbac(diff.add, acs, auth_provider_id, dry_run)
        if len(diff.delete) > 0:
            self.delete_rbac(diff.delete, acs, auth_provider_id, dry_run)
        if len(diff.change) > 0:
            self.update_rbac(diff.change, acs, auth_provider_id, dry_run)

    def run(
        self,
        dry_run: bool,
    ) -> None:
        gqlapi = gql.get_api()
        instance = self.get_acs_instance(gqlapi.query)

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        token = secret_reader.read_all_secret(instance.credentials)

        desired = self.get_desired_state(gqlapi.query)

        with AcsApi(
            instance={"url": instance.url, "token": token[instance.credentials.field]}
        ) as acs_api:
            current = self.get_current_state(acs_api, instance.auth_provider.q_id)
            self.reconcile(
                desired, current, acs_api, instance.auth_provider.q_id, dry_run
            )
