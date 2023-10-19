import logging
import requests

from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

from reconcile import queries
from reconcile.gql_definitions.acs.acs_rbac import (
    query as acs_rbac_query,
)
from reconcile.gql_definitions.acs.acs_instances import AcsInstanceV1
from reconcile.gql_definitions.acs.acs_instances import (
    query as acs_instances_query,
)

from reconcile.utils.acs_api import AcsApi
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
    ValidationError,
)


class AcsAccessScope(BaseModel):
    clusters: Optional[list[str]]
    namespaces: Optional[list[str]]


class AcsRole(BaseModel):
    name: str
    users: set[str]
    permission_set: str
    access_scope: AcsAccessScope


class AcsRbacIntegrationParams(PydanticRunParams):
    thread_pool_size: int


class AcsRbacIntegration(QontractReconcileIntegration[AcsRbacIntegrationParams]):
    def __init__(self, params: AcsRbacIntegrationParams) -> None:
        super().__init__(params)
        self.qontract_integration = "acs_rbac"
        self.qontract_integration_version = make_semver(0, 1, 0)
        self.qontract_tf_prefix = "qracsrbac"

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
        """Gets users with role refs containing acs permissions defined in App Interface
        and returns list of Acs roles with users

        :param query_func: function which queries GQL server and formats result
        :type query_func: Callable
        :return: list of AcsRole
        :rtype: AcsRole
        """
        desired: list[AcsRole] = []

        query_results = acs_rbac_query(query_func=query_func).acs_rbacs
        if query_results is None:
            return desired

        roles: dict[str, AcsRole] = {}
        for user in query_results:
            for role in user.roles:
                for permission in role.oidc_permissions:
                    if permission.service == "acs":
                        # A-I roles can reference multiple oidc-permissions
                        # leading to potential for duplicate names in ACS if A-I role names mapped to ACS roles
                        # Therefore, name of the oidc-permission is mapped to ACS role name
                        if permission.name not in roles:
                            roles[permission.name] = AcsRole(
                                name=permission.name,
                                users=set(user.org_username),
                                permission_set=permission.permission_set,
                                access_scope=AcsAccessScope(
                                    clusters=permission.clusters,
                                    namespaces=permission.namespaces,
                                ),
                            )
                        else:
                            # role accounted for from prior user. Append additional desired user
                            roles[permission.name].users.add(user.org_username)

        return list(roles.values())

    def get_existing_state(acs: AcsApi):
        pass

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Optional[Callable] = None,
    ) -> None:
        gqlapi = gql.get_api()
        # queries
        instance = self.get_acs_instance(gqlapi.query)
        desired = self.get_desired_state(gqlapi.query)

        acs = AcsApi(instance={"url": instance.url, "token": instance.token})

        existing = self.get_existing_state(acs)
