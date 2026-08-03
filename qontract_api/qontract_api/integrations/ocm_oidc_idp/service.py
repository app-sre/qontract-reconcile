"""OCM OIDC identity provider reconciliation service."""

from __future__ import annotations

import operator
from collections import Counter as CollectionCounter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import pydantic
from qontract_utils.differ import DiffPair, diff_iterables
from qontract_utils.ocm_api import OcmIdentityProvider, OcmIdentityProviderOidc
from qontract_utils.ocm_api.models import (
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
)

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
from qontract_api.ocm.ocm_client_factory import create_ocm_workspace_client
from qontract_api.rhidp.domain import SsoClientSecret, cluster_vault_secret_id

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.ocm.domain import OcmConnectionParams
    from qontract_api.ocm.ocm_workspace_client import OcmWorkspaceClient
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class _UnresolvedDesiredStateError(Exception):
    """Raised when a cluster's desired OIDC identity provider cannot be determined.

    Any current identity provider for this cluster must be excluded from the diff
    entirely - never treated as "not desired", which would delete a live, working
    configuration on e.g. a transient Vault read failure.

    `fatal` controls whether this also counts as a reconcile error: a not-yet-created
    Vault secret (sso_client hasn't reconciled this cluster yet) is a routine,
    extremely common condition and must never fail the reconcile - only a genuine
    misconfiguration (e.g. a stored issuer that doesn't match the cluster's
    configured one) should.
    """

    def __init__(self, message: str, *, fatal: bool) -> None:
        super().__init__(message)
        self.fatal = fatal


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
        workspace_client: OcmWorkspaceClient,
        clusters: list[OcmOidcIdpCluster],
        *,
        max_workers: int,
    ) -> list[_IdpState]:
        """Fetch existing identity providers for every cluster, concurrently.

        Each cluster's OCM query is an independent HTTP round-trip - fetching them
        serially would make wall-clock time scale linearly with cluster count, for
        no benefit (OcmWorkspaceClient already shares one OcmApi connection across
        threads). A single cluster's OCM query failing does not abort the whole run
        - it is logged and that cluster is skipped for this reconcile, matching the
        per-cluster error isolation used for desired-state secret reads below.
        """
        current_state: list[_IdpState] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_cluster = {
                executor.submit(
                    workspace_client.get_identity_providers, cluster.cluster_id
                ): cluster
                for cluster in clusters
            }
            for future in as_completed(future_to_cluster):
                cluster = future_to_cluster[future]
                try:
                    idps = future.result()
                except Exception:
                    logger.exception(
                        f"Failed to fetch identity providers for cluster "
                        f"{cluster.name}; skipping for this reconcile"
                    )
                    continue
                current_state.extend(
                    _IdpState(cluster=cluster, idp=idp) for idp in idps
                )
        return current_state

    def _fetch_desired_state(
        self, clusters: list[OcmOidcIdpCluster], vault_target: Secret
    ) -> tuple[list[_IdpState], set[tuple[str, str, str, str]], list[str]]:
        """Compile desired OIDC identity providers from sso_client's Vault secrets.

        Returns (desired_state, unresolved_keys, errors). unresolved_keys are diff
        keys (see reconcile()) whose desired state could not be determined - the
        caller must exclude any matching current-state entry from the diff, otherwise
        an unresolved cluster looks identical to "not desired" and its existing,
        working identity provider would be deleted. errors only ever contains
        *fatal* unresolved-state failures (see _UnresolvedDesiredStateError) - a
        not-yet-created Vault secret is routine and never ends up here.
        """
        desired_state: list[_IdpState] = []
        unresolved_keys: set[tuple[str, str, str, str]] = set()
        errors: list[str] = []
        for cluster in clusters:
            try:
                idp = self._desired_idp_for_cluster(cluster, vault_target)
            except _UnresolvedDesiredStateError as e:
                unresolved_keys.add((
                    cluster.organization_id,
                    cluster.name,
                    "OpenIDIdentityProvider",
                    cluster.auth.name,
                ))
                if e.fatal:
                    errors.append(str(e))
                continue
            if idp is not None:
                desired_state.append(_IdpState(cluster=cluster, idp=idp))
        return desired_state, unresolved_keys, errors

    def _desired_idp_for_cluster(
        self, cluster: OcmOidcIdpCluster, vault_target: Secret
    ) -> OcmIdentityProviderOidc | None:
        """Return the desired identity provider, or None if OIDC isn't desired.

        Raises _UnresolvedDesiredStateError (never for the cluster legitimately not
        wanting OIDC configured) if the desired state could not be determined - see
        that class's docstring for the fatal/non-fatal distinction.
        """
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
        # a routine, extremely common condition (sso_client hasn't reconciled this
        # cluster yet) - not fatal, not worth an error-level stack trace.
        except Exception as e:
            message = (
                f"{cluster.name}: unable to read or parse SSO client secret at "
                f"{secret.path}: {e}. Maybe not created yet?"
            )
            logger.warning(message)
            raise _UnresolvedDesiredStateError(message, fatal=False) from e

        if sso_client.issuer != cluster.auth.issuer:
            # Can only happen if someone manually changed or copied the secret - a
            # genuine misconfiguration, unlike the routine "not created yet" above.
            message = (
                f"{cluster.name}: SSO client issuer {sso_client.issuer} does not "
                f"match configured cluster issuer {cluster.auth.issuer}"
            )
            logger.error(message)
            raise _UnresolvedDesiredStateError(message, fatal=True)

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

    @staticmethod
    def _diff_key(state: _IdpState) -> tuple[str, str, str, str]:
        return (
            state.cluster.organization_id,
            state.cluster.name,
            state.idp.type,
            state.idp.name,
        )

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
        desired_state, unresolved_keys, errors = self._fetch_desired_state(
            clusters, vault_target
        )

        actions: list[OcmOidcIdpAction] = []
        applied_actions: list[OcmOidcIdpAction] = []
        # A single OcmWorkspaceClient (and the OcmApi connection it lazily builds)
        # is reused for every cluster's current-state fetch and every mutation below,
        # instead of re-authenticating with OCM on every single call.
        with create_ocm_workspace_client(
            ocm_connection, self.cache, self.secret_manager, self.settings
        ) as workspace_client:
            current_state = self._fetch_current_state(
                workspace_client,
                clusters,
                max_workers=self.settings.ocm.identity_providers_fetch_concurrency,
            )
            # A cluster whose desired state couldn't be resolved must never look
            # like "not desired" to the diff below - that would delete a live,
            # working identity provider on e.g. a transient Vault read failure.
            # Excluding its current-state entry entirely means no add/delete/change
            # action is ever computed for it this run.
            current_state = [
                state
                for state in current_state
                if self._diff_key(state) not in unresolved_keys
            ]

            diff_result = diff_iterables(
                current_state, desired_state, key=self._diff_key, equal=operator.eq
            )

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
