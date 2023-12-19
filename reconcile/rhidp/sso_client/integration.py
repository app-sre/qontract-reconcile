from reconcile.rhidp.common import (
    build_cluster_objects,
    discover_clusters,
    get_ocm_environments,
    get_ocm_orgs_from_env,
)
from reconcile.rhidp.sso_client.base import run
from reconcile.utils.ocm_base_client import init_ocm_base_client
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import VaultSecretReader

QONTRACT_INTEGRATION = "rhidp-sso-client"


class SSOClientParams(PydanticRunParams):
    keycloak_vault_paths: list[str]
    vault_input_path: str
    ocm_environment: str | None = None
    default_auth_name: str
    default_auth_issuer_url: str
    contacts: list[str]


class SSOClient(QontractReconcileIntegration[SSOClientParams]):
    """The RHIDP SSO Client integration manages SSO clients and uses OCM labels to discover clusters."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        secret_reader = VaultSecretReader()
        for ocm_env in get_ocm_environments(self.params.ocm_environment):
            ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
            cluster_details = discover_clusters(
                ocm_api=ocm_api,
                org_ids={
                    org.org_id for org in get_ocm_orgs_from_env(ocm_env.name, self.name)
                },
            )
            clusters = build_cluster_objects(
                cluster_details=cluster_details,
                default_auth_name=self.params.default_auth_name,
                default_issuer_url=self.params.default_auth_issuer_url,
            )
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
