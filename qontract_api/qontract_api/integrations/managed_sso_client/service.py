"""Managed SSO client (tenant-declared) reconciliation service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx2
from qontract_utils.secret_reader import SecretNotFoundError

from qontract_api.integrations.managed_sso_client.domain import (
    ManagedSsoClientManagementSecret,
    ManagedSsoClientTenantSecret,
)
from qontract_api.integrations.managed_sso_client.keycloak_client_factory import (
    build_keycloak_instances,
)
from qontract_api.integrations.managed_sso_client.metrics import (
    INTEGRATION_NAME,
    managed_sso_client_reconcile_errors,
    managed_sso_client_reconciled,
    managed_sso_client_token_persist_failures,
    managed_sso_clients_managed,
)
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientAction,
    ManagedSsoClientActionCreate,
    ManagedSsoClientActionDelete,
    ManagedSsoClientActionMoveTenantSecret,
    ManagedSsoClientActionUpdate,
    ManagedSsoClientTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import Secret, TaskStatus

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.managed_sso_client.domain import (
        ManagedSsoClientDesiredState,
    )
    from qontract_api.integrations.managed_sso_client.keycloak_workspace_client import (
        KeycloakWorkspaceClient,
    )
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class ManagedSsoClientTokenPersistError(Exception):
    """Token rotated on Keycloak but failed to persist to Vault - does not self-heal."""


class ManagedSsoClientService:
    """Reconciles tenant-declared managed SSO clients against Keycloak.

    Vault is the source of truth for which clients currently exist, since
    Keycloak's client-registration API has no "list clients" endpoint.
    """

    def __init__(
        self,
        secret_manager: SecretManager,
        cache: CacheBackend,
        settings: Settings,
        workspace_client_factory: Callable[..., dict[str, KeycloakWorkspaceClient]]
        | None = None,
    ) -> None:
        self.secret_manager = secret_manager
        self.cache = cache
        self.settings = settings
        self._workspace_client_factory = (
            workspace_client_factory or build_keycloak_instances
        )

    @staticmethod
    def _management_secret(vault_target: Secret, client_id: str) -> Secret:
        """Vault location of the AppSRE-owned secret for this client_id.

        Holds the full Keycloak registration response (incl. registration_access_token)
        under the shared management prefix - never synced to a tenant namespace.
        """
        return Secret(
            secret_manager_url=vault_target.secret_manager_url,
            path=f"{vault_target.path}/{client_id}",
        )

    def _tenant_secret(
        self, desired: ManagedSsoClientDesiredState, vault_target: Secret
    ) -> Secret:
        """Vault location of the tenant-facing credential secret for this client.

        Uses the caller's explicit `output` path if set, else an
        integration-managed default path keyed by client_id.
        """
        if desired.output:
            return desired.output
        return Secret(
            secret_manager_url=vault_target.secret_manager_url,
            path=(
                f"{self.settings.managed_sso_client.default_output_vault_path_prefix}"
                f"/{desired.client_id}"
            ),
        )

    def _read_management_secret(
        self, vault_target: Secret, client_id: str
    ) -> ManagedSsoClientManagementSecret | None:
        try:
            data = self.secret_manager.read_all(
                self._management_secret(vault_target, client_id)
            )
        except SecretNotFoundError:
            return None
        return ManagedSsoClientManagementSecret(**data)

    def _create_client(
        self,
        desired: ManagedSsoClientDesiredState,
        keycloak: KeycloakWorkspaceClient,
        vault_target: Secret,
    ) -> None:
        """Register a client with Keycloak and persist both its secrets."""
        tenant_secret = self._tenant_secret(desired, vault_target)
        registered = keycloak.register_client(desired.to_managed_keycloak_client())
        if registered.secret is None and not registered.public_client:
            msg = f"Keycloak did not return a client_secret for {desired.client_id}"
            raise ValueError(msg)
        management = ManagedSsoClientManagementSecret(
            client_id=registered.client_id,
            client_secret=registered.secret,
            registration_access_token=registered.registration_access_token or "",
            issuer=desired.keycloak_instance.url,
            tenant_secret_path=tenant_secret.path,
        )
        try:
            self.secret_manager.write(
                self._management_secret(vault_target, desired.client_id),
                management.model_dump(exclude_none=True),
            )
        except Exception:
            logger.exception(
                f"Failed to persist management secret for {desired.client_id}; "
                "rolling back Keycloak client registration"
            )
            try:
                keycloak.delete_client(
                    client_id=registered.client_id,
                    registration_access_token=(
                        registered.registration_access_token or ""
                    ),
                )
            except Exception:
                logger.exception(
                    f"Rollback also failed for {desired.client_id}; "
                    f"Keycloak client may be orphaned"
                )
            raise

        self.secret_manager.write(
            tenant_secret,
            ManagedSsoClientTenantSecret(
                client_id=management.client_id,
                client_secret=management.client_secret,
                issuer=management.issuer,
            ).model_dump(exclude_none=True),
        )

    def _move_tenant_secret(
        self,
        management: ManagedSsoClientManagementSecret,
        new_tenant_secret: Secret,
        vault_target: Secret,
    ) -> ManagedSsoClientManagementSecret:
        """Write the tenant secret to its newly-resolved path, then remove the old one.

        Reuses the client_secret Keycloak already issued - no Keycloak call
        needed, this is pure Vault bookkeeping for a changed `output` path.
        Writes the new copy before deleting the old one: if the write failed
        first, the client_secret (never re-readable from Keycloak) would be
        unrecoverable.
        """
        self.secret_manager.write(
            new_tenant_secret,
            ManagedSsoClientTenantSecret(
                client_id=management.client_id,
                client_secret=management.client_secret,
                issuer=management.issuer,
            ).model_dump(exclude_none=True),
        )
        old_tenant_secret = Secret(
            secret_manager_url=vault_target.secret_manager_url,
            path=management.tenant_secret_path,
        )
        try:
            self.secret_manager.delete(old_tenant_secret)
        except Exception:
            logger.exception(
                f"{management.client_id}: wrote tenant secret to the new output "
                f"path {new_tenant_secret.path!r} but failed to delete the old "
                f"copy at {old_tenant_secret.path!r} - it is now orphaned and "
                "will not be cleaned up automatically; delete it manually"
            )
        new_management = management.with_tenant_secret_path(new_tenant_secret.path)
        self.secret_manager.write(
            self._management_secret(vault_target, management.client_id),
            new_management.model_dump(exclude_none=True),
            force=True,
        )
        return new_management

    def _update_client(
        self,
        desired: ManagedSsoClientDesiredState,
        management: ManagedSsoClientManagementSecret,
        keycloak: KeycloakWorkspaceClient,
        vault_target: Secret,
    ) -> None:
        """Update a client's configuration on Keycloak via PUT.

        PUT rotates the registration access token immediately - the old one
        is invalid by the time this returns, so persisting the new one is
        not optional cleanup (see ManagedSsoClientTokenPersistError). Always
        performs the PUT unconditionally - the caller (_execute_action) is
        responsible for only calling this for a ManagedSsoClientActionUpdate,
        which _diff_client only ever emits when Keycloak-side drift was
        already confirmed, so this never re-fetches or re-compares.
        """
        updated = keycloak.update_client(
            client_id=desired.client_id,
            registration_access_token=management.registration_access_token,
            data=desired.to_managed_keycloak_client(),
        )
        new_token = (
            updated.registration_access_token or management.registration_access_token
        )
        new_management = management.with_registration_access_token(new_token)
        try:
            self.secret_manager.write(
                self._management_secret(vault_target, desired.client_id),
                new_management.model_dump(exclude_none=True),
                force=True,
            )
        except Exception as e:
            managed_sso_client_token_persist_failures.labels(INTEGRATION_NAME).inc()
            msg = (
                f"CRITICAL: client {desired.client_id} was updated in Keycloak "
                "(registration_access_token rotated) but persisting the new token "
                f"to Vault failed: {e}. Keycloak and Vault are now INCONSISTENT for "
                "this client - every future GET/PUT/DELETE will fail until this is "
                "fixed manually (re-run reconcile once Vault recovers, or delete "
                "and recreate the client if the token is unrecoverable)."
            )
            raise ManagedSsoClientTokenPersistError(msg) from e

    def _delete_client(
        self,
        client_id: str,
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> None:
        """Delete a client from Keycloak and remove its Vault secrets."""
        management_secret = self._management_secret(vault_target, client_id)
        management = ManagedSsoClientManagementSecret(
            **self.secret_manager.read_all(management_secret)
        )
        keycloak = keycloak_instances[management.issuer]
        try:
            keycloak.delete_client(
                client_id=management.client_id,
                registration_access_token=management.registration_access_token,
            )
        except httpx2.HTTPStatusError as e:
            if e.response.status_code not in {
                httpx2.codes.UNAUTHORIZED,
                httpx2.codes.NOT_FOUND,
            }:
                raise
            logger.warning(
                f"Failed to delete managed SSO client {client_id}, treating as "
                f"already deleted: {e}. Continuing to delete Vault secrets."
            )
        self.secret_manager.delete(management_secret)
        self.secret_manager.delete(
            Secret(
                secret_manager_url=vault_target.secret_manager_url,
                path=management.tenant_secret_path,
            )
        )

    def _execute_action(
        self,
        action: ManagedSsoClientAction,
        desired_by_id: dict[str, ManagedSsoClientDesiredState],
        management_by_id: dict[str, ManagedSsoClientManagementSecret],
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> None:
        """Execute a single action against Keycloak and Vault.

        For a client with both a move and an update action, the caller
        (reconcile) always orders the move first - it mutates
        management_by_id[client_id] in place so the update, if it runs
        after, persists the already-migrated tenant_secret_path instead of
        reverting it.
        """
        match action:
            case ManagedSsoClientActionCreate():
                logger.info(
                    f"Creating managed SSO client {action.client_id}",
                    action_type=action.action_type,
                    tenant_secret_path=action.tenant_secret_path,
                )
                desired = desired_by_id[action.client_id]
                keycloak = keycloak_instances[desired.keycloak_instance.url]
                self._create_client(desired, keycloak, vault_target)
            case ManagedSsoClientActionMoveTenantSecret():
                logger.info(
                    f"Moving tenant secret for managed SSO client {action.client_id}",
                    action_type=action.action_type,
                    tenant_secret_path=action.tenant_secret_path,
                )
                management = management_by_id[action.client_id]
                new_tenant_secret = Secret(
                    secret_manager_url=vault_target.secret_manager_url,
                    path=action.tenant_secret_path,
                )
                management_by_id[action.client_id] = self._move_tenant_secret(
                    management, new_tenant_secret, vault_target
                )
            case ManagedSsoClientActionUpdate():
                logger.info(
                    f"Updating managed SSO client {action.client_id}",
                    action_type=action.action_type,
                )
                desired = desired_by_id[action.client_id]
                management = management_by_id[action.client_id]
                keycloak = keycloak_instances[desired.keycloak_instance.url]
                self._update_client(desired, management, keycloak, vault_target)
            case ManagedSsoClientActionDelete():
                logger.info(
                    f"Deleting managed SSO client {action.client_id}",
                    action_type=action.action_type,
                )
                self._delete_client(action.client_id, keycloak_instances, vault_target)

    def _diff_client(
        self,
        desired: ManagedSsoClientDesiredState,
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> tuple[ManagedSsoClientAction | None, ManagedSsoClientManagementSecret]:
        """Diff a client's live Keycloak configuration against its desired state.

        Keycloak-only - a drifted tenant secret output path is an
        independent concern, checked separately by _diff_tenant_secret.
        """
        management = self._read_management_secret(vault_target, desired.client_id)
        if management is None:
            msg = "expected an existing management secret but found none"
            raise ValueError(msg)
        keycloak = keycloak_instances.get(desired.keycloak_instance.url)
        if keycloak is None:
            msg = (
                f"could not build a Keycloak client for {desired.keycloak_instance.url}"
            )
            raise ValueError(msg)
        current = keycloak.get_client(
            desired.client_id, management.registration_access_token
        )
        if desired.matches(current):
            return None, management
        return ManagedSsoClientActionUpdate(client_id=desired.client_id), management

    def _diff_tenant_secret(
        self,
        desired: ManagedSsoClientDesiredState,
        management: ManagedSsoClientManagementSecret,
        vault_target: Secret,
    ) -> ManagedSsoClientActionMoveTenantSecret | None:
        """Diff a client's recorded tenant secret path against its desired output.

        Independent of Keycloak-OIDC drift - an output-path-only change (no
        other field changed) must still be detected and migrated.
        """
        desired_tenant_secret = self._tenant_secret(desired, vault_target)
        if desired_tenant_secret.path == management.tenant_secret_path:
            return None
        return ManagedSsoClientActionMoveTenantSecret(
            client_id=desired.client_id,
            tenant_secret_path=desired_tenant_secret.path,
        )

    def _check_create_permission(
        self, desired: ManagedSsoClientDesiredState, vault_target: Secret
    ) -> None:
        """Verify Vault write access to both of this client's secret paths.

        Checked unconditionally for both the AppSRE-owned management secret
        and the tenant secret (default or custom output) - never assume
        either is writable, in the same order _create_client writes them.
        """
        for secret in (
            self._management_secret(vault_target, desired.client_id),
            self._tenant_secret(desired, vault_target),
        ):
            if not self.secret_manager.can_write(secret):
                msg = (
                    f"{desired.client_id}: qontract-api's Vault service "
                    f"account cannot write to {secret.path!r} - check the "
                    "Vault ACL"
                )
                raise ValueError(msg)

    def _check_for_update(
        self,
        desired: ManagedSsoClientDesiredState,
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> tuple[list[ManagedSsoClientAction], ManagedSsoClientManagementSecret]:
        """Diff a single already-tracked client - two independent checks.

        Raises with client_id always prefixed, regardless of which step
        fails - the caller is responsible for isolating one client's
        failure from the rest of reconcile. A move action, if any, is
        always ordered before an update action, since _execute_action
        relies on that order to migrate the tenant secret path before
        persisting an update's rotated registration_access_token.
        """
        try:
            keycloak_action, management = self._diff_client(
                desired, keycloak_instances, vault_target
            )
            tenant_secret_action = self._diff_tenant_secret(
                desired, management, vault_target
            )
        except Exception as e:
            raise ValueError(f"{desired.client_id}: {e}") from e
        actions = [
            action for action in (tenant_secret_action, keycloak_action) if action
        ]
        return actions, management

    def _calculate_actions(
        self,
        desired_by_id: dict[str, ManagedSsoClientDesiredState],
        keycloak_instances: dict[str, KeycloakWorkspaceClient],
        vault_target: Secret,
    ) -> tuple[
        list[ManagedSsoClientAction],
        dict[str, ManagedSsoClientManagementSecret],
        list[str],
    ]:
        """Diff desired client_ids against Vault-tracked existing client_ids.

        Vault only tracks which client_ids exist (plus credentials and instance
        info), not their live Keycloak configuration - that's fetched and
        compared per-client in _check_for_update, for whatever's in both sets.
        A new client (to_add) is also checked here for Vault write access to
        its tenant secret path - so a missing ACL is visible in dry-run
        instead of only failing after Keycloak registration.
        """
        existing_ids = set(self.secret_manager.list(vault_target))
        managed_sso_clients_managed.labels(INTEGRATION_NAME).set(len(existing_ids))
        desired_ids = set(desired_by_id)

        to_remove = sorted(existing_ids - desired_ids)
        to_add = sorted(desired_ids - existing_ids)
        to_check = sorted(existing_ids & desired_ids)

        actions: list[ManagedSsoClientAction] = [
            ManagedSsoClientActionDelete(client_id=client_id) for client_id in to_remove
        ]

        errors: list[str] = []
        management_by_id: dict[str, ManagedSsoClientManagementSecret] = {}

        for client_id in to_add:
            desired = desired_by_id[client_id]
            try:
                self._check_create_permission(desired, vault_target)
            except ValueError as e:
                errors.append(str(e))
                continue
            actions.append(
                ManagedSsoClientActionCreate(
                    client_id=client_id,
                    tenant_secret_path=self._tenant_secret(desired, vault_target).path,
                )
            )

        for client_id in to_check:
            try:
                client_actions, management = self._check_for_update(
                    desired_by_id[client_id], keycloak_instances, vault_target
                )
            except Exception as e:
                # _check_for_update's own messages already include client_id.
                error_msg = str(e)
                logger.exception(error_msg)
                errors.append(error_msg)
                continue
            actions.extend(client_actions)
            management_by_id[client_id] = management

        return actions, management_by_id, errors

    def reconcile(
        self,
        desired_clients: list[ManagedSsoClientDesiredState],
        *,
        dry_run: bool = True,
    ) -> ManagedSsoClientTaskResult:
        """Reconcile all tenant-declared managed SSO clients.

        The AppSRE-owned management Vault target is server-derived from
        settings, not caller-specified - keeps it out of client control and
        lets OPA restrict the calling token's role tightly (same rationale
        as SsoClientService.create_manual's target_secret).
        """
        vault_target = Secret(
            secret_manager_url=self.settings.secrets.default_provider_url,
            path=self.settings.managed_sso_client.vault_path_prefix,
        )
        desired_by_id = {client.client_id: client for client in desired_clients}
        keycloak_instances = self._workspace_client_factory(
            [client.keycloak_instance for client in desired_clients],
            self.cache,
            self.secret_manager,
            self.settings,
        )

        try:
            actions, management_by_id, errors = self._calculate_actions(
                desired_by_id, keycloak_instances, vault_target
            )

            applied_actions: list[ManagedSsoClientAction] = []
            if not dry_run:
                for action in actions:
                    try:
                        self._execute_action(
                            action,
                            desired_by_id,
                            management_by_id,
                            keycloak_instances,
                            vault_target,
                        )
                        applied_actions.append(action)
                    except Exception as e:
                        error_msg = (
                            f"{action.client_id}: Failed to execute action "
                            f"{action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)
        finally:
            for keycloak in keycloak_instances.values():
                keycloak.close()

        if errors:
            managed_sso_client_reconcile_errors.labels(INTEGRATION_NAME).inc()
        else:
            managed_sso_client_reconciled.labels(INTEGRATION_NAME).inc()

        return ManagedSsoClientTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
