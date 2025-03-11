import logging
from collections.abc import (
    Callable,
    Generator,
    Iterable,
)
from typing import Any

import yaml
from kubernetes.client import (  # type: ignore[attr-defined]
    ApiClient,
    V1ConfigMap,
    V1ObjectMeta,
)
from pydantic import BaseModel

import reconcile.openshift_base as ob
from reconcile.gql_definitions.automated_actions.instance import (
    AutomatedActionArgumentOpenshiftV1,
    AutomatedActionArgumentV1,
    AutomatedActionsInstanceV1,
    PermissionAutomatedActionsV1,
)
from reconcile.gql_definitions.automated_actions.instance import query as instance_query
from reconcile.utils import expiration, gql
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.oc import OCCli
from reconcile.utils.oc_map import init_oc_map_from_namespaces
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "automated-actions-config"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class AutomatedActionsConfigIntegrationParams(PydanticRunParams):
    thread_pool_size: int
    use_jump_host: bool
    internal: bool | None = None
    configmap_name: str = "automated-actions-config"


class AutomatedActionsRole(BaseModel):
    user: str
    role: str


class AutomatedActionsPolicy(BaseModel):
    sub: str
    obj: str
    params: dict[str, str] = {}


class AutomatedActionsConfigIntegration(
    QontractReconcileIntegration[AutomatedActionsConfigIntegrationParams]
):
    """Manage LDAP groups based on App-Interface roles."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query
        return {
            "automated_actions_instances": [
                c.dict() for c in self.get_automated_actions_instances(query_func)
            ]
        }

    def get_automated_actions_instances(
        self, query_func: Callable
    ) -> Generator[AutomatedActionsInstanceV1, None, None]:
        """Return all automated actions."""
        data = instance_query(query_func, variables={})
        for instance in data.automated_actions_instances_v1 or []:
            if instance.deployment.delete:
                continue
            instance.permissions = list(
                self._filter_permissions(instance.permissions or [])
            )
            yield instance

    def _is_enabled(self, argument: AutomatedActionArgumentV1) -> bool:
        """Check if the integration is enabled for the given argument namespace."""
        if isinstance(argument, AutomatedActionArgumentOpenshiftV1):
            return (
                integration_is_enabled("automated-actions", argument.namespace.cluster)
                and not argument.namespace.delete
            )
        return True

    def _filter_permissions(
        self, permissions: Iterable[PermissionAutomatedActionsV1]
    ) -> Generator[PermissionAutomatedActionsV1, None, None]:
        """Filter out expired roles and arguments (cluster.namespace) with disabled integrations."""
        for permission in permissions:
            # automated actions disabled for the cluster?
            permission.arguments = [
                arg for arg in permission.arguments or [] if self._is_enabled(arg)
            ]
            # remove expired roles
            permission.roles = expiration.filter(permission.roles)
            if not permission.roles:
                continue
            yield permission

    def _compile_roles(
        self, permissions: Iterable[PermissionAutomatedActionsV1]
    ) -> list[AutomatedActionsRole]:
        """Compile all automated actions roles."""
        roles: list[AutomatedActionsRole] = []
        for permission in permissions:
            for role in permission.roles or []:
                roles.extend(
                    AutomatedActionsRole(user=user.org_username, role=role.name)
                    for user in (role.users or []) + (role.bots or [])
                )
        return roles

    def _compile_policies(
        self, permissions: Iterable[PermissionAutomatedActionsV1]
    ) -> list[AutomatedActionsPolicy]:
        """Compile all automated actions policies."""
        policies: list[AutomatedActionsPolicy] = []
        for permission in permissions or []:
            obj = permission.action.operation_id

            parameters: list[dict[str, str]] = [] if permission.arguments else [{}]
            for arg in permission.arguments or []:
                match arg:
                    case AutomatedActionArgumentOpenshiftV1():
                        parameters.append({
                            "cluster": arg.namespace.cluster.name,
                            "namespace": arg.namespace.name,
                            "kind": arg.kind_pattern,
                            "name": arg.name_pattern,
                        })
                    case _:
                        raise NotImplementedError(
                            f"Unsupported argument type: {arg.q_type}"
                        )
            for role in permission.roles or []:
                policies.extend(
                    AutomatedActionsPolicy(sub=role.name, obj=obj, params=params)
                    for params in parameters
                )
        return policies

    def _build_policy_file(
        self,
        roles: Iterable[AutomatedActionsRole],
        policies: Iterable[AutomatedActionsPolicy],
    ) -> str:
        """Build the automated actions casbin policy file."""
        return yaml.dump({
            "g": [r.dict() for r in roles],
            "p": [p.dict() for p in policies],
        })

    def _build_desired_configmap(
        self,
        ri: ResourceInventory,
        instance: AutomatedActionsInstanceV1,
        name: str,
        data: str,
    ) -> None:
        """Build the automated actions configmap."""
        osr = OpenshiftResource(
            body=ApiClient().sanitize_for_serialization(
                V1ConfigMap(
                    api_version="v1",
                    kind="ConfigMap",
                    metadata=V1ObjectMeta(name=name),
                    data={"policy.yml": data},
                )
            ),
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
        ).annotate()
        ri.initialize_resource_type(
            cluster=instance.deployment.cluster.name,
            namespace=instance.deployment.name,
            resource_type=osr.kind,
        )
        ri.add_desired_resource(
            cluster=instance.deployment.cluster.name,
            namespace=instance.deployment.name,
            resource=osr,
        )

    def _fetch_current_configmap(
        self,
        ri: ResourceInventory,
        instance: AutomatedActionsInstanceV1,
        oc: OCCli,
        name: str,
    ) -> None:
        """Fetch the current automated actions configmap."""
        item = oc.get(
            namespace=instance.deployment.name,
            kind="ConfigMap",
            name=name,
            allow_not_found=True,
        )
        if not item:
            return
        osr = OpenshiftResource(
            body=item,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
        )
        ri.add_current(
            cluster=instance.deployment.cluster.name,
            namespace=instance.deployment.name,
            resource_type=osr.kind,
            name=osr.name,
            value=osr,
        )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        instances = list(self.get_automated_actions_instances(gql_api.query))
        if not instances:
            logging.debug("No instances found.")
            return

        oc_map = init_oc_map_from_namespaces(
            namespaces=[instance.deployment for instance in instances],
            secret_reader=self.secret_reader,
            integration=QONTRACT_INTEGRATION,
            use_jump_host=self.params.use_jump_host,
            thread_pool_size=self.params.thread_pool_size,
            internal=self.params.internal,
        )
        if defer:
            defer(oc_map.cleanup)
        ri = ResourceInventory()

        for instance in instances:
            automated_actions_roles = self._compile_roles(instance.permissions or [])
            automated_actions_policies = self._compile_policies(
                instance.permissions or []
            )
            if not automated_actions_roles and not automated_actions_policies:
                logging.info(
                    f"{instance.deployment.cluster.name}/{instance.deployment.name}: No enabled automated actions found. Skipping this instance!"
                )
                continue

            self._build_desired_configmap(
                ri=ri,
                instance=instance,
                name=self.params.configmap_name,
                data=self._build_policy_file(
                    automated_actions_roles, automated_actions_policies
                ),
            )

            oc = oc_map.get_cluster(instance.deployment.cluster.name)
            if not oc.project_exists(instance.deployment.name):
                logging.info(
                    f"{instance.deployment.cluster.name}/{instance.deployment.name}: Namespace does not exist (yet). Skipping this instance!"
                )
                continue

            self._fetch_current_configmap(
                ri=ri,
                instance=instance,
                oc=oc,
                name=self.params.configmap_name,
            )

        ob.publish_metrics(ri, QONTRACT_INTEGRATION)
        ob.realize_data(dry_run, oc_map, ri, self.params.thread_pool_size)
