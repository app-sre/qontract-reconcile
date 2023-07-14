import logging
import sys
from collections.abc import Callable
from typing import (
    Any,
    Optional,
)

from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.rhidp.common import get_clusters
from reconcile.rhidp.sso_client.base import run
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import VaultSecretReader

QONTRACT_INTEGRATION = "rhidp-sso-client"


class SSOClientIntegrationParams(PydanticRunParams):
    keycloak_vault_paths: list[str]
    vault_input_path: str
    default_auth_issuer_url: str
    contacts: list[str]


class SSOClientIntegration(
    QontractReconcileIntegration[SSOClientIntegrationParams],
):
    """A flavour of the RHIDP SSO Client integration, that receives the list of
    clusters from app-interface.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        clusters = self.get_clusters(gqlapi.query)
        # data query
        if not clusters:
            logging.debug("No clusters with oidc-idp definitions found.")
            sys.exit(ExitCodes.SUCCESS)

        run(
            integration_name=self.name,
            ocm_environment="all",
            clusters=clusters,
            secret_reader=VaultSecretReader(),
            keycloak_vault_paths=self.params.keycloak_vault_paths,
            vault_input_path=self.params.vault_input_path,
            contacts=self.params.contacts,
            dry_run=dry_run,
        )

    def get_clusters(self, query_func: Callable) -> list[ClusterV1]:
        return get_clusters(
            self.name,
            query_func,
            self.params.default_auth_issuer_url,
            exclude_clusters_without_ocm=False,
        )

    def get_early_exit_desired_state(self) -> Optional[dict[str, Any]]:
        gqlapi = gql.get_api()
        return {"clusters": [c.dict() for c in self.get_clusters(gqlapi.query)]}
