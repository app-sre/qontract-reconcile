"""RHIDP SSO client reconciliation service."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse, urlunparse

import httpx2
from jose import jwt

from qontract_api.integrations.sso_client.domain import (
    KeycloakInstanceIat,
    SsoClientSecret,
    cluster_vault_secret_id,
)
from qontract_api.integrations.sso_client.keycloak_client_factory import (
    build_keycloak_instances,
)
from qontract_api.integrations.sso_client.metrics import (
    INTEGRATION_NAME,
    rhidp_managed_clusters,
    rhidp_sso_client_inital_access_token_expiration,
    rhidp_sso_client_number_of_clients,
    rhidp_sso_client_reconcile_errors,
    rhidp_sso_client_reconciled,
)
from qontract_api.integrations.sso_client.schemas import (
    SsoClientAction,
    SsoClientActionCreate,
    SsoClientActionDelete,
    SsoClientTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import Secret, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.sso_client.domain import (
        KeycloakInstanceSecret,
        SsoClientCluster,
    )
    from qontract_api.integrations.sso_client.keycloak_workspace_client import (
        KeycloakWorkspaceClient,
    )
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


def console_url_to_oauth_url(console_url: str, auth_name: str) -> str:
    """Convert a cluster console URL to an OAuth callback URL.

    Ported from reconcile/rhidp/sso_client/base.py - ROSA and OSD clusters use
    different console URL patterns, and only the ROSA branch forces an explicit
    :443 port when none is present (an asymmetry preserved intentionally).
    """
    if console_url.startswith("https://console-openshift-console.apps.rosa."):
        # ROSA cluster
        url = urlparse(
            urljoin(
                console_url.replace("console-openshift-console.apps.rosa", "oauth"),
                f"/oauth2callback/{auth_name}",
            )
        )
        if url.port is None:
            url = url._replace(netloc=url.netloc + ":443")
        return urlunparse(url)
    # OSD cluster
    return urljoin(
        console_url.replace("console-openshift-console", "oauth-openshift"),
        f"/oauth2callback/{auth_name}",
    )


class SsoClientService:
    """Service for reconciling RHIDP SSO clients.

    Fetches current state (existing SSO client secrets in Vault), computes the diff
    against desired state (RHIDP-enabled clusters), and executes create/delete actions
    against Keycloak + Vault.

    Uses dependency injection to keep the service decoupled from implementation details.
    """

    def __init__(
        self,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self.cache = cache
        self.secret_manager = secret_manager
        self.settings = settings

    @staticmethod
    def _expose_cluster_metrics(
        ocm_environment: str, clusters: Iterable[SsoClientCluster]
    ) -> None:
        """Expose rhidp_managed_clusters per org, for ALL discovered clusters."""
        clusters_per_org: Counter[str] = Counter()
        for cluster in clusters:
            clusters_per_org[cluster.organization_id] += 1
        for org_id, count in clusters_per_org.items():
            rhidp_managed_clusters.labels(
                INTEGRATION_NAME, ocm_environment, org_id
            ).set(count)

    def _expose_iat_expiration_metrics(
        self, ocm_environment: str, keycloak_secrets: list[KeycloakInstanceSecret]
    ) -> None:
        for entry in keycloak_secrets:
            data = self.secret_manager.read_all(entry.secret)
            iat = KeycloakInstanceIat(**data)
            claims = jwt.get_unverified_claims(iat.current_iat.token)
            rhidp_sso_client_inital_access_token_expiration.labels(
                INTEGRATION_NAME, ocm_environment, entry.secret.path
            ).set(claims["exp"])

    def _create_sso_client(
        self,
        action: SsoClientActionCreate,
        cluster: SsoClientCluster,
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> bool:
        """Register the SSO client and store its secret. Returns False if skipped."""
        if not cluster.console_url:
            logger.error(
                f"Cluster {cluster.name} does not have a console URL; maybe not ready yet. Skipping for now."
            )
            return False

        keycloak = keycloak_instances[cluster.auth.issuer]
        sso_client = keycloak.register_client(
            client_name=action.sso_client_id,
            redirect_uris=[
                console_url_to_oauth_url(cluster.console_url, cluster.auth.name)
            ],
            group_filter_regex=cluster.auth.group_filter_regex,
        )
        secret_data = SsoClientSecret(
            client_id=sso_client.client_id,
            client_name=action.sso_client_id,
            client_secret=sso_client.client_secret,
            redirect_uris=sso_client.redirect_uris,
            registration_access_token=sso_client.registration_access_token,
            registration_client_uri=(
                f"{cluster.auth.issuer}/clients-registrations/default/{sso_client.client_id}"
            ),
            issuer=cluster.auth.issuer,
            attributes=sso_client.attributes,
        )
        try:
            self.secret_manager.write(
                Secret(
                    secret_manager_url=vault_target.secret_manager_url,
                    path=f"{vault_target.path}/{action.sso_client_id}",
                ),
                secret_data.model_dump(),
            )
        except Exception:
            logger.exception(
                f"Failed to persist secret for {action.sso_client_id}; "
                "rolling back Keycloak client registration"
            )
            keycloak.delete_client(
                client_id=sso_client.client_id,
                registration_access_token=sso_client.registration_access_token,
            )
            raise
        return True

    def _delete_sso_client(
        self,
        action: SsoClientActionDelete,
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> None:
        secret = Secret(
            secret_manager_url=vault_target.secret_manager_url,
            path=f"{vault_target.path}/{action.sso_client_id}",
        )
        secret_data = SsoClientSecret(**self.secret_manager.read_all(secret))
        keycloak = keycloak_instances[secret_data.issuer]
        try:
            keycloak.delete_client(
                client_id=secret_data.client_id,
                registration_access_token=secret_data.registration_access_token,
            )
        except httpx2.HTTPStatusError as e:
            if e.response.status_code not in {
                httpx2.codes.UNAUTHORIZED,
                httpx2.codes.NOT_FOUND,
            }:
                raise
            logger.warning(
                f"Failed to delete SSO client {action.sso_client_id}, "
                f"treating as already deleted: {e}. "
                "Continuing to delete the vault secret."
            )
        self.secret_manager.delete(secret)

    def _execute_action(
        self,
        action: SsoClientAction,
        clusters_by_id: dict[str, SsoClientCluster],
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> bool:
        """Execute a single action. Returns whether it was actually applied."""
        match action:
            case SsoClientActionCreate():
                logger.info(
                    f"Creating SSO client: {action.cluster_name}/{action.auth_name}",
                    action_type=action.action_type,
                    sso_client_id=action.sso_client_id,
                )
                return self._create_sso_client(
                    action,
                    clusters_by_id[action.sso_client_id],
                    keycloak_instances,
                    vault_target,
                )
            case SsoClientActionDelete():
                logger.info(
                    f"Deleting SSO client: {action.sso_client_id}",
                    action_type=action.action_type,
                    sso_client_id=action.sso_client_id,
                )
                self._delete_sso_client(action, keycloak_instances, vault_target)
                return True

    def reconcile(
        self,
        ocm_environment: str,
        clusters: list[SsoClientCluster],
        keycloak_secrets: list[KeycloakInstanceSecret],
        vault_target: Secret,
        *,
        dry_run: bool = True,
    ) -> SsoClientTaskResult:
        """Reconcile RHIDP SSO clients for one OCM environment."""
        self._expose_cluster_metrics(ocm_environment, clusters)
        self._expose_iat_expiration_metrics(ocm_environment, keycloak_secrets)
        keycloak_instances = build_keycloak_instances(
            keycloak_secrets, self.cache, self.secret_manager
        )

        existing_ids = self.secret_manager.list(vault_target)
        rhidp_sso_client_number_of_clients.labels(
            INTEGRATION_NAME, ocm_environment
        ).set(len(existing_ids))

        clusters_by_id = {
            cluster_vault_secret_id(
                cluster.organization_id,
                cluster.name,
                cluster.auth.name,
                cluster.auth.issuer,
            ): cluster
            for cluster in clusters
            if cluster.rhidp_enabled
        }

        to_remove = sorted(set(existing_ids) - set(clusters_by_id))
        to_add = sorted(set(clusters_by_id) - set(existing_ids))

        actions: list[SsoClientAction] = [
            SsoClientActionDelete(sso_client_id=sso_client_id)
            for sso_client_id in to_remove
        ] + [
            SsoClientActionCreate(
                sso_client_id=sso_client_id,
                cluster_name=clusters_by_id[sso_client_id].name,
                auth_name=clusters_by_id[sso_client_id].auth.name,
            )
            for sso_client_id in to_add
        ]

        applied_actions: list[SsoClientAction] = []
        errors: list[str] = []
        if not dry_run:
            for action in actions:
                try:
                    applied = self._execute_action(
                        action, clusters_by_id, keycloak_instances, vault_target
                    )
                    if applied:
                        applied_actions.append(action)
                except Exception as e:
                    error_msg = (
                        f"{action.sso_client_id}: Failed to execute action "
                        f"{action.action_type}: {e}"
                    )
                    logger.exception(error_msg)
                    errors.append(error_msg)

        if errors:
            rhidp_sso_client_reconcile_errors.labels(
                INTEGRATION_NAME, ocm_environment
            ).inc()
        else:
            rhidp_sso_client_reconciled.labels(INTEGRATION_NAME, ocm_environment).inc()

        return SsoClientTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
