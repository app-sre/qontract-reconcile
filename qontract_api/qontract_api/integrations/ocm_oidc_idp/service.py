"""OCM OIDC identity provider reconciliation service."""

from __future__ import annotations

import operator
from collections import Counter as CollectionCounter
from typing import TYPE_CHECKING

import pydantic
from qontract_utils.differ import DiffPair, diff_iterables
from qontract_utils.ocm_api import OcmIdentityProvider, OcmIdentityProviderOidc
from qontract_utils.ocm_api.models import (
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
)

from qontract_api.external.ocm.ocm_client_factory import create_ocm_workspace_client
from qontract_api.integrations.ocm_oidc_idp.domain import OcmOidcIdpCluster
from qontract_api.integrations.ocm_oidc_idp.metrics import (
    INTEGRATION_NAME,
    rhidp_managed_clusters,
    rhidp_ocm_oidc_idp_reconcile_errors,
    rhidp_ocm_oidc_idp_reconciled,
)
from qontract_api.integrations.ocm_oidc_idp.schemas import (
    OcmOidcIdpAction,
    OcmOidcIdpActionCreate,
    OcmOidcIdpActionDelete,
    OcmOidcIdpActionUpdate,
    OcmOidcIdpTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import Secret, TaskStatus
from qontract_api.rhidp.domain import SsoClientSecret, cluster_vault_secret_id

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.external.ocm.ocm_workspace_client import OcmWorkspaceClient
    from qontract_api.external.ocm.schemas import OcmConnectionParams
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class _IdpState(pydantic.BaseModel):
    """Internal diffing unit: one identity provider + the cluster it belongs to.

    Equality is delegated to the identity provider only (see
    OcmIdentityProviderOidc.__eq__), so the diff never flags a "change" purely
    because cluster metadata differs while the IDP itself is unchanged.
    """

    cluster: OcmOidcIdpCluster
    idp: OcmIdentityProvider | OcmIdentityProviderOidc

    # Custom __eq__ delegates to idp only, so instances are intentionally
    # unhashable. mypy has no clean way to type this pattern outside of @dataclass.
    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _IdpState):
            return NotImplemented
        return self.idp == other.idp


class OcmOidcIdpService:
    """Service for reconciling OCM OIDC identity providers.

    Fetches current state (existing identity providers per cluster, from OCM) and
    desired state (from the SSO client secrets sso_client wrote to Vault), diffs
    them, and executes create/update/delete actions against OCM.

    Uses dependency injection to keep the service decoupled from implementation
    details.
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
        ocm_environment: str, clusters: Iterable[OcmOidcIdpCluster]
    ) -> None:
        """Expose rhidp_managed_clusters per org, for ALL discovered clusters."""
        clusters_per_org: CollectionCounter[str] = CollectionCounter()
        for cluster in clusters:
            clusters_per_org[cluster.organization_id] += 1
        for org_id, count in clusters_per_org.items():
            rhidp_managed_clusters.labels(
                INTEGRATION_NAME, ocm_environment, org_id
            ).set(count)

    @staticmethod
    def _fetch_current_state(
        workspace_client: OcmWorkspaceClient, clusters: list[OcmOidcIdpCluster]
    ) -> list[_IdpState]:
        """Fetch existing identity providers for every cluster.

        A single cluster's OCM query failing does not abort the whole run - it is
        logged and that cluster is skipped for this reconcile, matching the
        per-cluster error isolation used for desired-state secret reads below.
        """
        current_state: list[_IdpState] = []
        for cluster in clusters:
            try:
                idps = workspace_client.get_identity_providers(cluster.cluster_id)
            except Exception:
                logger.exception(
                    f"Failed to fetch identity providers for cluster {cluster.name}; "
                    "skipping for this reconcile"
                )
                continue
            current_state.extend(_IdpState(cluster=cluster, idp=idp) for idp in idps)
        return current_state

    def _fetch_desired_state(
        self, clusters: list[OcmOidcIdpCluster], vault_target: Secret
    ) -> list[_IdpState]:
        """Compile desired OIDC identity providers from sso_client's Vault secrets."""
        desired_state: list[_IdpState] = []
        for cluster in clusters:
            idp = self._desired_idp_for_cluster(cluster, vault_target)
            if idp is not None:
                desired_state.append(_IdpState(cluster=cluster, idp=idp))
        return desired_state

    def _desired_idp_for_cluster(
        self, cluster: OcmOidcIdpCluster, vault_target: Secret
    ) -> OcmIdentityProviderOidc | None:
        if not cluster.auth.oidc_enabled:
            return None

        secret_id = cluster_vault_secret_id(
            cluster.organization_id,
            cluster.name,
            cluster.auth.name,
            cluster.auth.issuer,
        )
        secret = Secret(
            secret_manager_url=vault_target.secret_manager_url,
            path=f"{vault_target.path}/{secret_id}",
        )
        try:
            sso_client = SsoClientSecret(**self.secret_manager.read_all(secret))
        # Intentionally broad: the secret backend (pluggable per ADR-017) and
        # pydantic validation can raise open-ended exception types here, and this is
        # a routine, expected condition (sso_client may not have created the secret
        # yet) - not worth an error-level stack trace.
        except Exception as e:  # ruff: ignore[blind-except]
            logger.warning(
                f"Unable to read or parse SSO client secret at {secret.path}: {e}. "
                f"Maybe not created yet? Skipping OIDC config for cluster "
                f"{cluster.name}"
            )
            return None

        if sso_client.issuer != cluster.auth.issuer:
            # Can only happen if someone manually changed or copied the secret.
            logger.error(
                f"SSO client issuer {sso_client.issuer} does not match configured "
                f"cluster issuer {cluster.auth.issuer}. Skipping OIDC config for "
                f"cluster {cluster.name}"
            )
            return None

        claims = OcmIdentityProviderOidcOpenIdClaims(
            groups=["filtered_groups"]
            if sso_client.attributes.get("group-filter-regex")
            else [],
        )
        return OcmIdentityProviderOidc(
            name=cluster.auth.name,
            open_id=OcmIdentityProviderOidcOpenId(
                client_id=sso_client.client_id,
                client_secret=sso_client.client_secret,
                issuer=cluster.auth.issuer,
                claims=claims,
            ),
        )

    @staticmethod
    def _process_deletes(
        workspace_client: OcmWorkspaceClient,
        delete_states: Iterable[_IdpState],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmOidcIdpAction], list[OcmOidcIdpAction], list[str]]:
        actions: list[OcmOidcIdpAction] = []
        applied: list[OcmOidcIdpAction] = []
        errors: list[str] = []

        for idp_state in delete_states:
            if (
                idp_state.idp.name != idp_state.cluster.auth.name
                and not idp_state.cluster.auth.enforced
            ):
                logger.debug(
                    f"Skipping removal of unmanaged '{idp_state.idp.name}' IDP on "
                    f"cluster {idp_state.cluster.name}."
                )
                continue
            if idp_state.idp.id is None:
                errors.append(
                    f"{idp_state.cluster.name}: identity provider "
                    f"{idp_state.idp.name} has no id, cannot delete"
                )
                continue

            action = OcmOidcIdpActionDelete(
                cluster_name=idp_state.cluster.name, idp_name=idp_state.idp.name
            )
            actions.append(action)
            if dry_run:
                continue
            try:
                workspace_client.delete_identity_provider(
                    idp_state.cluster.cluster_id, idp_state.idp.id
                )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{idp_state.cluster.name}: failed to delete identity provider "
                    f"{idp_state.idp.name}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    @staticmethod
    def _process_adds(
        workspace_client: OcmWorkspaceClient,
        add_states: Iterable[_IdpState],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmOidcIdpAction], list[OcmOidcIdpAction], list[str]]:
        actions: list[OcmOidcIdpAction] = []
        applied: list[OcmOidcIdpAction] = []
        errors: list[str] = []

        for idp_state in add_states:
            if not isinstance(idp_state.idp, OcmIdentityProviderOidc):
                logger.error(
                    f"Desired identity provider {idp_state.idp.name} on cluster "
                    f"{idp_state.cluster.name} is not an OIDC identity provider."
                )
                continue

            action = OcmOidcIdpActionCreate(
                cluster_name=idp_state.cluster.name, auth_name=idp_state.idp.name
            )
            actions.append(action)
            if dry_run:
                continue
            try:
                workspace_client.create_identity_provider(
                    idp_state.cluster.cluster_id, idp_state.idp
                )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{idp_state.cluster.name}: failed to create identity provider "
                    f"{idp_state.idp.name}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    @staticmethod
    def _process_changes(
        workspace_client: OcmWorkspaceClient,
        change_pairs: Iterable[DiffPair[_IdpState, _IdpState]],
        *,
        dry_run: bool,
    ) -> tuple[list[OcmOidcIdpAction], list[OcmOidcIdpAction], list[str]]:
        actions: list[OcmOidcIdpAction] = []
        applied: list[OcmOidcIdpAction] = []
        errors: list[str] = []

        for diff_pair in change_pairs:
            current_idp = diff_pair.current.idp
            desired_idp = diff_pair.desired.idp
            cluster = diff_pair.desired.cluster

            if not isinstance(desired_idp, OcmIdentityProviderOidc):
                logger.error(
                    f"Desired identity provider {desired_idp.name} on cluster "
                    f"{cluster.name} is not an OIDC identity provider."
                )
                continue
            if current_idp.id is None:
                errors.append(
                    f"{cluster.name}: identity provider {current_idp.name} has no "
                    "id, cannot update"
                )
                continue

            action = OcmOidcIdpActionUpdate(
                cluster_name=cluster.name, auth_name=desired_idp.name
            )
            actions.append(action)
            if dry_run:
                continue
            try:
                workspace_client.update_identity_provider(
                    cluster.cluster_id, current_idp.id, desired_idp
                )
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{cluster.name}: failed to update identity provider "
                    f"{desired_idp.name}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)

        return actions, applied, errors

    def reconcile(
        self,
        ocm_environment: str,
        ocm_connection: OcmConnectionParams,
        clusters: list[OcmOidcIdpCluster],
        vault_target: Secret,
        *,
        dry_run: bool = True,
    ) -> OcmOidcIdpTaskResult:
        """Reconcile OCM OIDC identity providers for one OCM environment."""
        self._expose_cluster_metrics(ocm_environment, clusters)
        workspace_client = create_ocm_workspace_client(
            ocm_connection, self.cache, self.secret_manager, self.settings
        )

        current_state = self._fetch_current_state(workspace_client, clusters)
        desired_state = self._fetch_desired_state(clusters, vault_target)

        diff_result = diff_iterables(
            current_state,
            desired_state,
            key=lambda s: (
                s.cluster.organization_id,
                s.cluster.name,
                s.idp.type,
                s.idp.name,
            ),
            equal=operator.eq,
        )

        actions: list[OcmOidcIdpAction] = []
        applied_actions: list[OcmOidcIdpAction] = []
        errors: list[str] = []
        for category_actions, category_applied, category_errors in (
            self._process_deletes(
                workspace_client, diff_result.delete.values(), dry_run=dry_run
            ),
            self._process_adds(
                workspace_client, diff_result.add.values(), dry_run=dry_run
            ),
            self._process_changes(
                workspace_client, diff_result.change.values(), dry_run=dry_run
            ),
        ):
            actions.extend(category_actions)
            applied_actions.extend(category_applied)
            errors.extend(category_errors)

        if errors:
            rhidp_ocm_oidc_idp_reconcile_errors.labels(
                INTEGRATION_NAME, ocm_environment
            ).inc()
        else:
            rhidp_ocm_oidc_idp_reconciled.labels(
                INTEGRATION_NAME, ocm_environment
            ).inc()

        return OcmOidcIdpTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
