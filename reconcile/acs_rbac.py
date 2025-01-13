import logging
from collections import defaultdict
from collections.abc import Callable
from itertools import starmap
from typing import (
    Self,
)

from pydantic import BaseModel

from reconcile.gql_definitions.acs.acs_rbac import OidcPermissionAcsV1
from reconcile.gql_definitions.acs.acs_rbac import query as acs_rbac_query
from reconcile.utils import gql
from reconcile.utils.acs.rbac import AcsRbacApi, Group, RbacResources
from reconcile.utils.differ import (
    DiffPair,
    diff_iterables,
)
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
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
    system_default: bool | None

    @classmethod
    def build(cls, permission: Permission, usernames: list[str]) -> Self:
        assignments = [
            AssignmentPair(
                # org_username attribute from https://github.com/app-sre/qontract-schemas/blob/main/schemas/access/user-1.yml
                # is mapped to userid key in auth rules.
                key="userid",
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
            for role in user.roles or []:
                for permission in role.oidc_permissions or []:
                    if isinstance(permission, OidcPermissionAcsV1):
                        permission_usernames[
                            Permission(**permission.dict(by_alias=True))
                        ].append(user.org_username)
        return list(starmap(AcsRole.build, permission_usernames.items()))

    def get_current_state(
        self, auth_provider_id: str, rbac_api_resources: RbacResources
    ) -> list[AcsRole]:
        """
        Get current ACS roles and associated users from ACS api

        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :return: list of current AcsRole associated with specified auth provider
        """
        current_roles: list[AcsRole] = []

        role_assignments: RoleAssignments = self.build_role_assignments(
            auth_provider_id, rbac_api_resources.groups
        )
        access_scope_id_map = {s.id: s for s in rbac_api_resources.access_scopes}
        permission_sets_id_map = {
            ps.id: ps for ps in rbac_api_resources.permission_sets
        }

        for role in rbac_api_resources.roles:
            # process roles that are not system default
            # OR
            # system default roles referenced in auth rules
            # however, do not reconcile the auth provider minimum access rule associated with 'None' system default
            if not role.system_default or (
                role.name in role_assignments and role.name != "None"
            ):
                access_scope = access_scope_id_map[role.access_scope_id]
                permission_set = permission_sets_id_map[role.permission_set_id]

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

    def add_rbac_for_role(
        self,
        role: AcsRole,
        acs: AcsRbacApi,
        admin_access_scope_id: str,
        permission_set_id: str,
        auth_id: str,
        dry_run: bool,
    ) -> None:
        """
        Creates rbac resources associated with an AcsRole

        :param role: AcsRole to create
        :param acs: ACS api client
        :param admin_access_scope_id: id of system default 'Unrestricted' access scope
        :param permission_set_id: id of permission set resource to assign to created role
        :param auth_id: id of auth provider to target for creation of rbac resources
        :param dry_run: run in dry-run mode
        """

        # skip access scope creation and use existing system default 'Unrestricted' access scope if unrestricted
        # note: this serves to reduce redundant admin scopes but also due to restriction within api when
        # attempting to provision another admin access scope
        if not role.is_unrestricted_scope():
            # recall that a desired role and access scope are derived from a single oidc-permission-1
            # therefore, items in diff.add require creation of dependency access scope first and then role
            if not dry_run:
                as_id = acs.create_access_scope(
                    role.access_scope.name,
                    role.access_scope.description,
                    role.access_scope.clusters,
                    role.access_scope.namespaces,
                )
            logging.info("Created access scope: %s", role.access_scope.name)

        if not dry_run:
            acs.create_role(
                role.name,
                role.description,
                permission_set_id,
                admin_access_scope_id if role.is_unrestricted_scope() else as_id,
            )
        logging.info("Created role: %s", role.name)

        if not dry_run:
            additions = [
                AcsRbacApi.GroupAdd(
                    role_name=role.name,
                    key=a.key,
                    value=a.value,
                    auth_provider_id=auth_id,
                )
                for a in role.assignments
            ]
            acs.create_group_batch(additions)
        logging.info(
            "Added users to role %s: %s",
            role.name,
            [a.value for a in role.assignments],
        )

    def add_rbac(
        self,
        to_add: dict[str, AcsRole],
        rbac_api_resources: RbacResources,
        acs: AcsRbacApi,
        auth_id: str,
        dry_run: bool,
    ) -> list[Exception]:
        """
        Creates desired ACS roles as well as associated access scopes and rules

        :param to_add: result of 'diff_iterables(current, desired).add' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in rbac_api_resources.access_scopes}
        permission_sets_id_map = {
            ps.name: ps.id for ps in rbac_api_resources.permission_sets
        }
        errors = []
        for role in to_add.values():
            try:
                self.add_rbac_for_role(
                    role=role,
                    acs=acs,
                    admin_access_scope_id=access_scope_id_map[DEFAULT_ADMIN_SCOPE_NAME],
                    permission_set_id=permission_sets_id_map[role.permission_set_name],
                    auth_id=auth_id,
                    dry_run=dry_run,
                )
            except Exception as e:
                errors.append(e)
        return errors

    def delete_rbac_for_role(
        self,
        role: AcsRole,
        acs: AcsRbacApi,
        access_scope_id: str,
        admin_access_scope_id: str,
        groups: list[Group],
        dry_run: bool,
    ) -> None:
        """
        Deletes rbac resources associated with an AcsRole

        :param role: AcsRole to delete
        :param acs: ACS api client
        :param access_scope_id: id of access scope resource associated with role
        :param groups: list of groups (auth rules) referencing the role
        :param dry_run: run in dry-run mode
        """

        # role and associated resources must be deleted in the proceeding order
        if not dry_run:
            acs.delete_group_batch(groups)
        logging.info(
            "Deleted users from role %s: %s",
            role.name,
            [a.value for a in role.assignments],
        )
        # only delete rules associated with a system default roles
        # do not continue to deletion of the role and associated access scope
        if role.system_default:
            return

        if not dry_run:
            acs.delete_role(role.name)
        logging.info("Deleted role: %s", role.name)

        # do not attempt deletion of system default 'Unrestricted' scope referenced by a custom role
        if access_scope_id != admin_access_scope_id:
            if not dry_run:
                acs.delete_access_scope(access_scope_id)
            logging.info("Deleted access scope: %s", role.access_scope.name)

    def delete_rbac(
        self,
        to_delete: dict[str, AcsRole],
        rbac_api_resources: RbacResources,
        acs: AcsRbacApi,
        auth_id: str,
        dry_run: bool,
    ) -> list[Exception]:
        """
        Deletes desired ACS roles as well as associated access scopes and rules

        :param to_delete: result of 'diff_iterables(current, desired).delete' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in rbac_api_resources.access_scopes}
        role_group_mappings: dict[str, list[Group]] = defaultdict(list)
        for group in rbac_api_resources.groups:
            if group.auth_provider_id == auth_id:
                role_group_mappings[group.role_name].append(group)

        errors = []
        for role in to_delete.values():
            try:
                self.delete_rbac_for_role(
                    role=role,
                    acs=acs,
                    access_scope_id=access_scope_id_map[role.access_scope.name],
                    admin_access_scope_id=access_scope_id_map[DEFAULT_ADMIN_SCOPE_NAME],
                    groups=role_group_mappings[role.name],
                    dry_run=dry_run,
                )
            except Exception as e:
                errors.append(e)
        return errors

    def update_rbac_for_role(
        self,
        role_diff_pair: DiffPair[AcsRole, AcsRole],
        acs: AcsRbacApi,
        role_group_mappings: dict[str, dict[str, Group]],
        access_scope_id: str,
        permission_set_id: str,
        auth_id: str,
        dry_run: bool,
    ) -> None:
        """
        Updates rbac resources associated with an AcsRole

        :param role_diff_pair: pair of AcsRole representing current and desired
        :param acs: ACS api client
        :param role_group_mappings: maps role names to names of groups referencing roles
                                    to data of the group
        :param access_scope_id: id of access scope resource associated with role
        :param groups: list of groups (auth rules) referencing the role
        :param dry_run: run in dry-run mode
        """

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
                AcsRbacApi.GroupAdd(
                    role_name=role_diff_pair.desired.name,
                    key=a.key,
                    value=a.value,
                    auth_provider_id=auth_id,
                )
                for a in diff.add.values()
            ]
            if not dry_run:
                acs.update_group_batch(old, new)
            logging.info(
                "Updated rules for role '%s':\n" + "\tAdded: %s\n" + "\tDeleted: %s",
                role_diff_pair.desired.name,
                [n.value for n in new],
                [o.value for o in old],
            )
        # access scope portion
        if role_diff_pair.current.access_scope != role_diff_pair.desired.access_scope:
            if not dry_run:
                acs.update_access_scope(
                    access_scope_id,
                    role_diff_pair.desired.access_scope.name,
                    role_diff_pair.desired.access_scope.description,
                    role_diff_pair.desired.access_scope.clusters,
                    role_diff_pair.desired.access_scope.namespaces,
                )
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
                acs.update_role(
                    role_diff_pair.desired.name,
                    role_diff_pair.desired.description,
                    permission_set_id,
                    access_scope_id,
                )
            logging.info("Updated role: %s", role_diff_pair.desired.name)

    def update_rbac(
        self,
        to_update: dict[str, DiffPair[AcsRole, AcsRole]],
        rbac_api_resources: RbacResources,
        acs: AcsRbacApi,
        auth_id: str,
        dry_run: bool,
    ) -> list[Exception]:
        """
        Updates desired ACS roles as well as associated access scopes and rules

        :param to_update: result of 'diff_iterables(current, desired).change' for ACS roles
        :param acs: ACS api client
        :param auth_id: id of auth provider within ACS instance to target for reconciliation
        :param dry_run: run in dry-run mode
        """
        access_scope_id_map = {s.name: s.id for s in rbac_api_resources.access_scopes}
        permission_sets_id_map = {
            ps.name: ps.id for ps in rbac_api_resources.permission_sets
        }
        role_group_mappings: dict[str, dict[str, Group]] = defaultdict(dict)
        for group in rbac_api_resources.groups:
            role_group_mappings[group.role_name][group.value] = group

        errors = []
        for role_diff_pair in to_update.values():
            try:
                self.update_rbac_for_role(
                    role_diff_pair=role_diff_pair,
                    acs=acs,
                    role_group_mappings=role_group_mappings,
                    access_scope_id=access_scope_id_map[
                        role_diff_pair.desired.access_scope.name
                    ],
                    permission_set_id=permission_sets_id_map[
                        role_diff_pair.desired.permission_set_name
                    ],
                    auth_id=auth_id,
                    dry_run=dry_run,
                )
            except Exception as e:
                errors.append(e)
        return errors

    def reconcile(
        self,
        desired: list[AcsRole],
        current: list[AcsRole],
        rbac_api_resources: RbacResources,
        acs: AcsRbacApi,
        auth_provider_id: str,
        dry_run: bool,
    ) -> None:
        errors = []
        diff = diff_iterables(current, desired, lambda x: x.name)
        if len(diff.add) > 0:
            errors.extend(
                self.add_rbac(
                    to_add=diff.add,
                    rbac_api_resources=rbac_api_resources,
                    acs=acs,
                    auth_id=auth_provider_id,
                    dry_run=dry_run,
                )
            )
        if len(diff.delete) > 0:
            errors.extend(
                self.delete_rbac(
                    to_delete=diff.delete,
                    rbac_api_resources=rbac_api_resources,
                    acs=acs,
                    auth_id=auth_provider_id,
                    dry_run=dry_run,
                )
            )
        if len(diff.change) > 0:
            errors.extend(
                self.update_rbac(
                    to_update=diff.change,
                    rbac_api_resources=rbac_api_resources,
                    acs=acs,
                    auth_id=auth_provider_id,
                    dry_run=dry_run,
                )
            )
        if errors:
            raise ExceptionGroup("Reconcile errors occurred", errors)

    def run(
        self,
        dry_run: bool,
    ) -> None:
        gqlapi = gql.get_api()
        instance = AcsRbacApi.get_acs_instance(gqlapi.query)
        desired = self.get_desired_state(gqlapi.query)

        with AcsRbacApi(
            url=instance.url, token=self.secret_reader.read_secret(instance.credentials)
        ) as acs_api:
            rbac_api_resources = acs_api.get_rbac_resources()
            current = self.get_current_state(
                instance.auth_provider.q_id, rbac_api_resources
            )
            self.reconcile(
                desired=desired,
                current=current,
                rbac_api_resources=rbac_api_resources,
                acs=acs_api,
                auth_provider_id=instance.auth_provider.q_id,
                dry_run=dry_run,
            )
