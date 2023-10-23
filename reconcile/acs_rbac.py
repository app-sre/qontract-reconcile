import logging

from collections.abc import Callable
from typing import (
    Optional,
)

from reconcile.gql_definitions.acs.acs_rbac import (
    query as acs_rbac_query,
    OidcPermissionAcsV1,
)
from reconcile.gql_definitions.acs.acs_instances import AcsInstanceV1
from reconcile.gql_definitions.acs.acs_instances import (
    query as acs_instances_query,
)

from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.secret_reader import (
    create_secret_reader,
)

from reconcile.utils.acs_api import AcsApi, Group
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import (
    DiffResult,
    diff_iterables,
)
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

from pydantic import (
    BaseModel,
)


class AssignmentPair(BaseModel):
    key: str
    value: str


RoleAssignments = dict[str, list[AssignmentPair]]


class AcsAccessScope(BaseModel):
    name: str
    description: str
    clusters: list[str]
    namespaces: list[dict[str, str]]


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


class AcsRbacIntegrationParams(PydanticRunParams):
    thread_pool_size: int


class AcsRbacIntegration(QontractReconcileIntegration[AcsRbacIntegrationParams]):
    def __init__(self, params: AcsRbacIntegrationParams) -> None:
        super().__init__(params)
        self.qontract_integration = "acs_rbac"
        self.qontract_integration_version = make_semver(0, 1, 0)
        self.qontract_tf_prefix = "qracsrbac"

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    def get_acs_instance(self, query_func: Callable) -> AcsInstanceV1:
        """Get an ACS instance."""
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

        :param query_func: function which queries GQL server and formats result
        :type query_func: Callable
        :return: list of AcsRole
        :rtype: AcsRole
        """

        query_results = acs_rbac_query(query_func=query_func).acs_rbacs
        if query_results is None:
            return []

        desired_roles: dict[str, AcsRole] = {}
        for user in query_results:
            for role in user.roles or []:
                for permission in role.oidc_permissions or []:
                    if isinstance(permission, OidcPermissionAcsV1):
                        # first encounter of specific permission
                        # derive the Acs role specifics and add initial user
                        if permission.name not in desired_roles:
                            desired_roles[permission.name] = AcsRole(
                                name=permission.name,
                                description=permission.description,
                                assignments=[
                                    AssignmentPair(
                                        key="org_username", value=user.org_username
                                    )
                                ],
                                permission_set_name=permission.permission_set,
                                access_scope=AcsAccessScope(
                                    name=permission.name,
                                    description=permission.description,
                                    # second arg is returned even if first arg == False
                                    clusters=[
                                        cluster.name
                                        for cluster in (permission.clusters or [])
                                    ],
                                    namespaces=[
                                        {
                                            "clusterName": n.cluster.name,
                                            "namespaceName": n.name,
                                        }
                                        for n in (permission.namespaces or [])
                                    ],
                                ),
                            )
                        else:
                            # role accounted for by prior user ref. Append additional desired user
                            desired_roles[permission.name].assignments.append(
                                AssignmentPair(
                                    key="org_username", value=user.org_username
                                )
                            )

        return list(desired_roles.values())

    def get_existing_state(self, acs: AcsApi, auth_id: str) -> list[AcsRole]:
        """
        Get existing ACS roles and associated users from ACS api

        :param acs: acs api client
        :return: list of AcsRole
        :rtype: AcsRole
        """
        existing_roles: dict[str, AcsRole] = {}
        try:
            roles = acs.get_roles()
        except Exception as e:
            raise Exception(f"Failed to retrieve existing roles: {e}")

        try:
            groups = acs.get_groups()
        except Exception as e:
            raise Exception(f"Failed to retrieve existing role assignments: {e}")

        role_assignments: RoleAssignments = self.build_role_assignments(auth_id, groups)

        for role in roles:
            # only process roles referenced by users or generated via A-I
            if role.name in role_assignments or not role.system_default:
                try:
                    access_scope = acs.get_access_scope_by_id(role.access_scope_id)
                except Exception as e:
                    logging.error(
                        f"Failed to retrieve existing access scope: {role.access_scope_id} for role: {role.name}\t\n{e}"
                    )
                    continue

                try:
                    permission_set = acs.get_permission_set_by_id(
                        role.permission_set_id
                    )
                except Exception as e:
                    logging.error(
                        f"Failed to retrieve existing permission set: {role.permission_set_id} for role: {role.name}\t\n{e}"
                    )
                    continue

                existing_roles[role.name] = AcsRole(
                    name=role.name,
                    description=role.description,
                    assignments=role_assignments[role.name],
                    permission_set_name=permission_set.name,
                    access_scope=AcsAccessScope(
                        name=access_scope.name,
                        description=access_scope.description,
                        clusters=access_scope.clusters,
                        namespaces=access_scope.namespaces,
                    ),
                )

        return list(existing_roles.values())

    def build_role_assignments(
        self, auth_id: str, groups: list[Group]
    ) -> RoleAssignments:
        """
        Processes Groups returned by ACS api and maps roles to users
        A "group" in ACS api is an object that acts as assignment of a user to a role

        :param auth_id: the authProviderId to process for
        :param groups: list of Group objects received from api
        :return: map in which keys are role names and values are list of user attributes
        :rtype: RoleAssignment
        """
        auth_rules: RoleAssignments = {}
        for group in groups:
            # part of auth provider specified in A-I to reconcile (internal SSO)
            if group.auth_id == auth_id:
                if group.role_name in auth_rules:
                    auth_rules[group.role_name].append(
                        AssignmentPair(key=group.key, value=group.value)
                    )
                else:
                    auth_rules[group.role_name] = [
                        AssignmentPair(key=group.key, value=group.value)
                    ]
        return auth_rules

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Optional[Callable] = None,
    ) -> None:
        gqlapi = gql.get_api()
        instance = self.get_acs_instance(gqlapi.query)

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        token = secret_reader.read_all_secret(instance.credentials)

        acs = AcsApi(
            instance={"url": instance.url, "token": token[instance.credentials.field]}
        )

        desired = self.get_desired_state(gqlapi.query)
        existing = self.get_existing_state(acs, auth_id=instance.auth_provider.q_id)

        print(desired)
        print(existing)
