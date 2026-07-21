"""RHIDP SSO client reconciliation via qontract-api.

Differences from reconcile/rhidp/sso_client:
- Suffix '_api' indicates API-based integration
- OCM cluster discovery happens via qontract-api's GET /external/ocm/clusters
  endpoint (see ADR-013: external calls through qontract-api), not directly against OCM
- Business logic (Keycloak client create/delete, Vault secret bookkeeping) happens
  server-side (qontract-api); only label interpretation (which label means what) stays
  client-side here
- Keycloak instance secrets (initial-access-tokens) live in a different Vault instance
  than everything else - keycloak_instances carries each instance's URL and its own
  Vault location (secret_manager_url + path) explicitly
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qontract_api_client.client import ocm_clusters, sso_client
from qontract_api_client.schemas import (
    KeycloakInstanceSecret,
    Secret,
    SsoClientAuth,
    SsoClientCluster,
    SsoClientReconcileRequest,
    SsoClientTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.rhidp_api.common import (
    AUTH_NAME_LABEL_KEY,
    GROUP_FILTER_REGEX_LABEL_KEY,
    ISSUER_LABEL_KEY,
    RHIDP_NAMESPACE_LABEL_KEY,
    STATUS_LABEL_KEY,
    StatusValue,
    get_ocm_environments,
    get_ocm_orgs_from_env,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api_client.schemas import OcmClusterInfo

QONTRACT_INTEGRATION = "rhidp-sso-client-api"


class SSOClientApiIntegrationParams(PydanticRunParams):
    """Parameters for rhidp-sso-client-api integration."""

    keycloak_instances: list[KeycloakInstanceSecret]
    vault_input_path: str
    ocm_environment: str | None = None
    default_auth_name: str
    default_auth_issuer_url: str


def build_clusters(
    clusters: Iterable[OcmClusterInfo],
    default_auth_name: str,
    default_issuer_url: str,
) -> list[SsoClientCluster]:
    """Compile SsoClientCluster desired-state objects from discovered OCM clusters.

    Label interpretation stays client-side: which labels mean what, and the default
    fallbacks, mirror reconcile/rhidp/common.py::build_cluster_objects exactly. Clusters
    without a console URL or with external auth enabled can never get an SSO client and
    are excluded entirely (not even counted toward rhidp_managed_clusters).
    """
    result: list[SsoClientCluster] = []
    for cluster in clusters:
        if not cluster.console_url or cluster.external_auth_enabled:
            continue

        labels: dict[str, Any] = cluster.labels or {}
        status = (
            labels.get(RHIDP_NAMESPACE_LABEL_KEY)
            or labels.get(STATUS_LABEL_KEY)
            or StatusValue.DISABLED.value
        )
        result.append(
            SsoClientCluster(
                name=cluster.name,
                organization_id=cluster.organization_id,
                console_url=cluster.console_url,
                rhidp_enabled=status != StatusValue.DISABLED.value,
                auth=SsoClientAuth(
                    name=labels.get(AUTH_NAME_LABEL_KEY) or default_auth_name,
                    issuer=labels.get(ISSUER_LABEL_KEY) or default_issuer_url,
                    group_filter_regex=labels.get(GROUP_FILTER_REGEX_LABEL_KEY),
                ),
            )
        )
    return result


class SSOClientApiIntegration(
    QontractReconcileApiIntegration[SSOClientApiIntegrationParams]
):
    """Manage RHIDP SSO clients via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def async_run(self, dry_run: bool) -> None:
        for ocm_env in get_ocm_environments(self.params.ocm_environment):
            org_ids = [
                org.org_id for org in get_ocm_orgs_from_env(ocm_env.name, self.name)
            ]
            clusters_response = await ocm_clusters(
                ocm_url=ocm_env.url,
                access_token_url=ocm_env.access_token_url,
                access_token_client_id=ocm_env.access_token_client_id,
                secret_manager_url=self.secret_manager_url,
                path=ocm_env.access_token_client_secret.path,
                field=ocm_env.access_token_client_secret.field,
                version=ocm_env.access_token_client_secret.version,
                label_key_prefix=RHIDP_NAMESPACE_LABEL_KEY,
                org_ids=org_ids,
            )
            clusters = build_clusters(
                clusters_response.clusters,
                self.params.default_auth_name,
                self.params.default_auth_issuer_url,
            )

            vault_target = Secret(
                secret_manager_url=self.secret_manager_url,
                # put secrets in a subpath per OCM environment to avoid deleting
                # clusters from other environments
                path=f"{self.params.vault_input_path}/{ocm_env.name}",
            )
            request = SsoClientReconcileRequest(
                ocm_environment=ocm_env.name,
                clusters=clusters,
                keycloak_secrets=self.params.keycloak_instances,
                vault_target=vault_target,
                dry_run=dry_run,
            )

            task = await sso_client(request)
            # Always log the request id! It won't be forwarded to #reconcile channel
            # via fluentd filter!
            logging.info(f"request_id: {task.id}")

            if not dry_run:
                # In non-dry-run, the task completes asynchronously in the background
                # and change events are published automatically via the events framework.
                continue

            task_result = await self.poll_task_status(
                status_url=task.status_url, result_type=SsoClientTaskResult
            )
            if task_result.status == TaskStatus.PENDING:
                raise IntegrationError(
                    f"{QONTRACT_INTEGRATION}: task did not complete within the timeout period"
                )

            for action in task_result.actions or []:
                logging.info(f"{action.action_type=} {action.sso_client_id=}")

            if task_result.errors:
                errors_summary = "; ".join(task_result.errors)
                raise IntegrationError(
                    f"{QONTRACT_INTEGRATION}: {len(task_result.errors)} error(s): {errors_summary}"
                )
