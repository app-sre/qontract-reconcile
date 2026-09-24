from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

from deepdiff import DeepHash
from qontract_utils.managed_sso_client import (
    DEFAULT_OUTPUT_VAULT_PATH_PREFIX,
    derive_managed_sso_client_id,
)

import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb
from reconcile.gql_definitions.openshift_managed_sso_client_secret.namespaces import (
    NamespaceOpenshiftResourceManagedSsoClientV1,
    NamespaceV1,
    SharedResourcesV1_NamespaceOpenshiftResourceV1_NamespaceOpenshiftResourceManagedSsoClientV1,
)
from reconcile.gql_definitions.openshift_managed_sso_client_secret.namespaces import (
    query as managed_sso_client_secrets_query,
)
from reconcile.utils import gql
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.oc_map import init_oc_map_from_namespaces
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory, ResourceKeyExistsError
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretNotFoundError
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from reconcile.gql_definitions.openshift_managed_sso_client_secret.namespaces import (
        ManagedSsoClientV1,
        SharedResourcesV1_NamespaceOpenshiftResourceV1_NamespaceOpenshiftResourceManagedSsoClientV1_ManagedSsoClientV1,
    )
    from reconcile.utils.secret_reader import SecretReaderBase

    # openshiftResources is a NamespaceOpenshiftResource_v1 interface field, and
    # the `... on NamespaceOpenshiftResourceManagedSsoClient_v1 { ... }` type
    # condition is written at two separate query paths (top-level and
    # sharedResources-nested) to get qenerate to emit a proper discriminated
    # union at each - see namespaces.gql. That produces two structurally
    # identical but nominally distinct classes per level instead of one
    # shared type, hence these union aliases.
    AnyManagedSsoClientV1 = (
        ManagedSsoClientV1
        | SharedResourcesV1_NamespaceOpenshiftResourceV1_NamespaceOpenshiftResourceManagedSsoClientV1_ManagedSsoClientV1
    )

# Real (non-TYPE_CHECKING) alias: used in isinstance() below, not just annotations.
AnyManagedSsoClientResourceV1 = (
    NamespaceOpenshiftResourceManagedSsoClientV1
    | SharedResourcesV1_NamespaceOpenshiftResourceV1_NamespaceOpenshiftResourceManagedSsoClientV1
)

QONTRACT_INTEGRATION = "openshift-managed-sso-client-secrets"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class OpenshiftManagedSsoClientSecretsIntegrationParams(PydanticRunParams):
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE
    internal: bool | None = None
    cluster_name: list[str] | None = None
    namespace_name: str | None = None
    vault_path_prefix: str = DEFAULT_OUTPUT_VAULT_PATH_PREFIX


class OpenshiftManagedSsoClientSecretsIntegration(
    QontractReconcileIntegration[OpenshiftManagedSsoClientSecretsIntegrationParams]
):
    """Delivers a managed-sso-client's tenant-facing Vault credentials as an OpenShift Secret."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    def get_namespaces(self, query_func: Callable) -> list[NamespaceV1]:
        result: list[NamespaceV1] = []
        for ns in (
            managed_sso_client_secrets_query(query_func=query_func).namespaces or []
        ):
            ob.aggregate_shared_resources_typed(ns)
            if (
                integration_is_enabled(self.name, ns.cluster)
                and not bool(ns.delete)
                and (
                    not self.params.cluster_name
                    or ns.cluster.name in self.params.cluster_name
                )
                # Matches openshift_resources_base.canonicalize_namespaces'
                # own `if ors and providers:` filter - the same rule every
                # other openshiftResources-based integration in this
                # codebase (vault-secret, route, resource, ...) relies on.
                # Without it, init_specs_to_fetch would build an unbounded
                # (resource_names=None) "list every Secret" CurrentStateSpec
                # for every namespace on every enabled cluster, not just ones
                # this integration actually manages. Same known trade-off as
                # those integrations: removing the last managed resource from
                # openshiftResources can leave a stale Secret behind, uncleaned,
                # until another resource is added back to that namespace.
                and self.managed_sso_client_resources(ns)
            ):
                result.append(ns)
        return result

    def managed_sso_client_resources(
        self, ns: NamespaceV1
    ) -> list[AnyManagedSsoClientResourceV1]:
        """Narrow openshiftResources to managed-sso-client entries only.

        openshiftResources is heterogeneous (any provider a namespace declares
        - vault-secret, route, resource, ...), and GraphQL only resolves this
        integration's fragment fields for items actually of type
        NamespaceOpenshiftResourceManagedSsoClient_v1 - other items come back
        with none of those fields set. isinstance narrows to just the matching
        items instead of assuming every entry is one of ours.
        """
        return [
            r
            for r in ns.openshift_resources or []
            if isinstance(r, AnyManagedSsoClientResourceV1)
        ]

    def tenant_secret_vault_path(self, client: AnyManagedSsoClientV1) -> str:
        """Resolve the Vault path of a managed-sso-client's tenant-facing secret."""
        if client.output:
            return client.output
        client_id = derive_managed_sso_client_id(client.app.name, client.name)
        return f"{self.params.vault_path_prefix}/{client_id}"

    def construct_managed_sso_client_secret(
        self,
        resource: AnyManagedSsoClientResourceV1,
        client: AnyManagedSsoClientV1,
        secret_data: Mapping[str, str],
    ) -> OR:
        name = resource.name or client.name
        body: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {"name": name},
            "stringData": dict(secret_data),
        }
        if resource.labels:
            body["metadata"]["labels"] = resource.labels
        if resource.annotations:
            body["metadata"]["annotations"] = resource.annotations
        return OR(body, self.name, self.integration_version)

    def fetch_desired_state(
        self,
        namespaces: list[NamespaceV1],
        ri: ResourceInventory,
        secret_reader: SecretReaderBase,
        dry_run: bool,
    ) -> None:
        for ns in namespaces:
            for resource in self.managed_sso_client_resources(ns):
                self._add_desired_secret(
                    ns,
                    resource,
                    resource.managed_sso_client,
                    ri,
                    secret_reader,
                    dry_run,
                )

    def _add_desired_secret(
        self,
        ns: NamespaceV1,
        resource: AnyManagedSsoClientResourceV1,
        client: AnyManagedSsoClientV1,
        ri: ResourceInventory,
        secret_reader: SecretReaderBase,
        dry_run: bool,
    ) -> None:
        vault_path = self.tenant_secret_vault_path(client)
        try:
            secret_data = secret_reader.read_all({"path": vault_path})
        except SecretNotFoundError:
            logging.warning(
                f"[{ns.cluster.name}/{ns.name}] managed-sso-client "
                f"'{client.name}' tenant secret not found at Vault path "
                f"'{vault_path}' - has managed-sso-client-api reconciled "
                "it yet? Skipping until it exists."
            )
            # A brand-new client's secret can't exist before the app-interface
            # MR declaring it is merged, so the pr_check dry run for that same
            # MR would always hit this path - hard-failing here would make an
            # MR that adds a client and wires it into a namespace together
            # permanently unable to pass its own CI gate. Only register a hard
            # error on real runs, where a still-missing secret is a meaningful
            # signal for monitoring.
            if not dry_run:
                ri.register_error(cluster=ns.cluster.name)
            return
        secret = self.construct_managed_sso_client_secret(resource, client, secret_data)
        try:
            ri.add_desired_resource(
                cluster=ns.cluster.name,
                namespace=ns.name,
                resource=secret,
            )
        except ResourceKeyExistsError:
            # Two managed-sso-client resources in the same namespace can
            # resolve to the same Secret name (e.g. two clients both named
            # "ci-bot", or a duplicate between a namespace's own resource and
            # a shared one). openshift_resources_base.fetch_desired_state has
            # this identical handling - without it, add_desired_resource's
            # raise propagates unhandled through run(), aborting every
            # cluster instead of just the affected one.
            logging.error(
                f"[{ns.cluster.name}/{ns.name}] duplicate Secret name "
                f"'{secret.name}' for managed-sso-client '{client.name}'"
            )
            ri.register_error(cluster=ns.cluster.name)

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        # orb.fetch_current_state() wraps every fetched object with these
        # module-level globals as its "integration" identity - without this,
        # should_delete()'s has_qontract_annotations() check compares against
        # openshift_resources_base's own default name, never matches this
        # integration's own previously-applied secrets, and this integration
        # could never clean up its own now-obsolete secrets.
        orb.QONTRACT_INTEGRATION = self.name
        orb.QONTRACT_INTEGRATION_VERSION = self.integration_version
        gql_api = gql.get_api()
        namespaces = self.get_namespaces(gql_api.query)
        if self.params.namespace_name:
            namespaces = [
                ns for ns in namespaces if ns.name == self.params.namespace_name
            ]
        if not namespaces:
            logging.debug(
                "No managed-sso-client openshift resources found in app-interface"
            )
            return
        oc_map = init_oc_map_from_namespaces(
            namespaces=namespaces,
            integration=self.name,
            secret_reader=self.secret_reader,
            internal=self.params.internal,
            thread_pool_size=self.params.thread_pool_size,
        )
        if defer:
            defer(oc_map.cleanup)
        ri = ResourceInventory()
        state_specs = ob.init_specs_to_fetch(
            ri,
            oc_map,
            namespaces=[ns.model_dump(by_alias=True) for ns in namespaces],
            override_managed_types=["Secret"],
        )
        for spec in state_specs:
            if isinstance(spec, ob.CurrentStateSpec):
                orb.fetch_current_state(
                    spec.oc,
                    ri,
                    spec.cluster,
                    spec.namespace,
                    spec.kind,
                    spec.resource_names,
                )
        self.fetch_desired_state(namespaces, ri, self.secret_reader, dry_run)
        ob.realize_data(dry_run, oc_map, ri, self.params.thread_pool_size)
        ob.publish_metrics(ri, self.name)
        if ri.has_error_registered():
            sys.exit(1)

    def get_early_exit_desired_state(self) -> dict[str, Any] | None:
        state_for_clusters: dict[str, list[dict[str, Any]]] = {}
        for ns in self.get_namespaces(gql.get_api().query):
            state_for_clusters.setdefault(ns.cluster.name, []).append(
                ns.model_dump(by_alias=True)
            )
        return {
            "state": {
                cluster: {"shard": cluster, "hash": DeepHash(state).get(state)}
                for cluster, state in state_for_clusters.items()
            }
        }

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="cluster_name",
            shard_arg_is_collection=True,
            shard_path_selectors={
                "state.*.shard",
            },
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )
