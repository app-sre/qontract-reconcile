from typing import Optional

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.common import (
    build_cluster_auths,
    build_cluster_obj,
    discover_clusters,
)
from reconcile.rhidp.sso_client.base import run
from reconcile.utils import gql
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import VaultSecretReader

QONTRACT_INTEGRATION = "rhidp-sso-client-standalone"


class SSOClientStandaloneParams(PydanticRunParams):
    keycloak_vault_paths: list[str]
    vault_input_path: str
    ocm_environment: Optional[str] = None
    ocm_organization_ids: Optional[set[str]] = None
    auth_name: str
    auth_issuer_url: str
    contacts: list[str]


class SSOClientStandalone(QontractReconcileIntegration[SSOClientStandaloneParams]):
    """A flavour of the RHDID SSO Client integration, that uses OCM labels to discover clusters."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        secret_reader = VaultSecretReader()
        for ocm_env in self.get_ocm_environments():
            ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
            clusters = self.get_clusters(ocm_api=ocm_api, ocm_env=ocm_env)

            run(
                integration_name=self.name,
                ocm_environment=ocm_env.name,
                clusters=clusters,
                secret_reader=secret_reader,
                keycloak_vault_paths=self.params.keycloak_vault_paths,
                # put secrets in a subpath per OCM environment to avoid deleting
                # clusters from other environments
                vault_input_path=f"{self.params.vault_input_path}/{ocm_env.name}",
                contacts=self.params.contacts,
                dry_run=dry_run,
            )

    def get_clusters(
        self,
        ocm_api: OCMBaseClient,
        ocm_env: OCMEnvironment,
    ) -> list[ClusterV1]:
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=self.params.ocm_organization_ids,
        )

        return [
            build_cluster_obj(
                ocm_env=ocm_env,
                cluster=c,
                auth=build_cluster_auths(
                    name=self.params.auth_name,
                    issuer_url=self.params.auth_issuer_url,
                ),
            )
            for ocm_clusters in clusters_by_org.values()
            for c in ocm_clusters
        ]

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment
            else None,
        ).environments
