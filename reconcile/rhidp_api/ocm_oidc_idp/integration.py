"""OCM OIDC identity provider reconciliation via qontract-api.

Differences from reconcile/rhidp/ocm_oidc_idp:
- Suffix '_api' indicates API-based integration
- OCM cluster discovery happens via qontract-api's GET /external/ocm/clusters
  endpoint (see ADR-013: external calls through qontract-api), not directly against OCM
- Business logic (fetching current OCM identity providers, diffing against the SSO
  client secrets sso_client wrote to Vault, executing create/update/delete) happens
  server-side (qontract-api); only label interpretation (which label means what)
  stays client-side here
- Does NOT create Keycloak/SSO clients - that's rhidp_api/sso_client's job. This
  integration only reconciles the OCM-side identity provider config pointing at the
  already-registered SSO client (coupled only via the Vault secret sso_client
  writes and this integration reads server-side)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from qontract_api_client.client import ocm_clusters, ocm_oidc_idp
from qontract_api_client.schemas import (
    OcmConnectionParams,
    OcmOidcIdpAuth,
    OcmOidcIdpCluster,
    OcmOidcIdpReconcileRequest,
    OcmOidcIdpTaskResult,
    Secret,
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

QONTRACT_INTEGRATION = "ocm-oidc-idp-api"


class OCMOidcIdpApiIntegrationParams(PydanticRunParams):
    """Parameters for ocm-oidc-idp-api integration."""

    vault_input_path: str
    ocm_environment: str | None = None
    default_auth_name: str
    default_auth_issuer_url: str


def build_clusters(
    clusters: Iterable[OcmClusterInfo],
    default_auth_name: str,
    default_issuer_url: str,
) -> list[OcmOidcIdpCluster]:
    """Compile OcmOidcIdpCluster desired-state objects from discovered OCM clusters.

    Label interpretation stays client-side: which labels mean what, and the status
    semantics (oidc_enabled/enforced), mirror reconcile/rhidp/common.py::ClusterAuth
    exactly. Clusters without a console URL or with external auth enabled are
    excluded entirely, mirroring reconcile/rhidp/common.py::build_cluster_objects.
    Clusters labeled `ignored` are excluded entirely too - unlike `disabled`, which
    is still sent so the server can clean up a stale identity provider.
    """
    result: list[OcmOidcIdpCluster] = []
    for cluster in clusters:
        if not cluster.console_url or cluster.external_auth_enabled:
            continue

        labels: dict[str, Any] = cluster.labels or {}
        if labels.get(STATUS_LABEL_KEY) == StatusValue.IGNORED.value:
            continue

        status = (
            labels.get(RHIDP_NAMESPACE_LABEL_KEY)
            or labels.get(STATUS_LABEL_KEY)
            or StatusValue.DISABLED.value
        )
        result.append(
            OcmOidcIdpCluster(
                cluster_id=cluster.id,
                name=cluster.name,
                organization_id=cluster.organization_id,
                auth=OcmOidcIdpAuth(
                    name=labels.get(AUTH_NAME_LABEL_KEY) or default_auth_name,
                    issuer=labels.get(ISSUER_LABEL_KEY) or default_issuer_url,
                    group_filter_regex=labels.get(GROUP_FILTER_REGEX_LABEL_KEY),
                    oidc_enabled=status
                    not in {StatusValue.DISABLED.value, StatusValue.RHIDP_ONLY.value},
                    enforced=status == StatusValue.ENFORCED.value,
                ),
            )
        )
    return result


class OCMOidcIdpApiIntegration(
    QontractReconcileApiIntegration[OCMOidcIdpApiIntegrationParams]
):
    """Manage OCM OIDC identity providers via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def async_run(self, dry_run: bool) -> None:
        for ocm_env in get_ocm_environments(self.params.ocm_environment):
            org_ids = [
                org.org_id for org in get_ocm_orgs_from_env(ocm_env.name, self.name)
            ]
            with self.log_api_exceptions():
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

            ocm_connection = OcmConnectionParams(
                secret_manager_url=self.secret_manager_url,
                path=ocm_env.access_token_client_secret.path,
                field=ocm_env.access_token_client_secret.field,
                version=ocm_env.access_token_client_secret.version,
                ocm_url=ocm_env.url,
                access_token_url=ocm_env.access_token_url,
                access_token_client_id=ocm_env.access_token_client_id,
            )
            vault_target = Secret(
                secret_manager_url=self.secret_manager_url,
                # Must match rhidp_api/sso_client's own per-environment vault_target
                # suffix exactly - both integrations read/write the same secrets.
                path=f"{self.params.vault_input_path}/{ocm_env.name}",
            )
            request = OcmOidcIdpReconcileRequest(
                ocm_environment=ocm_env.name,
                ocm_connection=ocm_connection,
                clusters=clusters,
                vault_target=vault_target,
                dry_run=dry_run,
            )

            with self.log_api_exceptions():
                task = await ocm_oidc_idp(request)
            # Always log the request id! It won't be forwarded to #reconcile channel
            # via fluentd filter!
            logging.info(f"request_id: {task.id}")

            if not dry_run:
                # In non-dry-run, the task completes asynchronously in the background
                # and change events are published automatically via the events framework.
                continue

            task_result = await self.poll_task_status(
                status_url=task.status_url, result_type=OcmOidcIdpTaskResult
            )
            if task_result.status == TaskStatus.PENDING:
                raise IntegrationError(
                    f"{QONTRACT_INTEGRATION}: task did not complete within the timeout period"
                )

            for action in task_result.actions or []:
                logging.info(f"{action.action_type=} {action.cluster_name=}")

            if task_result.errors:
                errors_summary = "; ".join(task_result.errors)
                raise IntegrationError(
                    f"{QONTRACT_INTEGRATION}: {len(task_result.errors)} error(s): {errors_summary}"
                )
