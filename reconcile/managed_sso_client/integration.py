"""Managed SSO client (tenant-declared) reconciliation via qontract-api.

Client-side integration: compiles desired state for tenant-declared SSO
clients from App-Interface's managed-sso-client-1.yml objects and sends it to
qontract-api for reconciliation against Keycloak.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qontract_api_client.client import (
    managed_sso_client as reconcile_managed_sso_client,
)
from qontract_api_client.schemas import (
    KeycloakInstanceRef,
    ManagedSsoClientActionCreate,
    ManagedSsoClientActionDelete,
    ManagedSsoClientActionMoveTenantSecret,
    ManagedSsoClientActionUpdate,
    ManagedSsoClientDesiredState,
    ManagedSsoClientReconcileRequest,
    ManagedSsoClientTaskResponse,
    ManagedSsoClientTaskResult,
    OidcDesiredState,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.managed_sso_client.managed_sso_client import (
    ManagedSsoClientOidcV1,
    ManagedSsoClientOpenidConnectV1,
    ManagedSsoClientV1,
)
from reconcile.gql_definitions.managed_sso_client.managed_sso_client import (
    query as managed_sso_clients_query,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

QONTRACT_INTEGRATION = "managed-sso-client"


class ManagedSsoClientIntegrationParams(PydanticRunParams):
    """Parameters for managed-sso-client integration."""


class ManagedSsoClientIntegration(
    QontractReconcileApiIntegration[ManagedSsoClientIntegrationParams]
):
    """Manage tenant-declared SSO clients via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_managed_sso_clients(
        query_func: Callable[..., dict[Any, Any]],
    ) -> list[ManagedSsoClientV1]:
        data = managed_sso_clients_query(query_func=query_func)
        return list(data.managed_sso_clients or [])

    @staticmethod
    def _compile_oidc(oidc: ManagedSsoClientOidcV1) -> OidcDesiredState:
        """Compile OIDC desired state.

        GraphQL returns null for the optional arrays that were never set in
        App-Interface. Pass those through as None rather than resolving to a
        default: the server treats an unset field as "don't manage this"
        (Keycloak's PUT merges by field and never touches it), whereas
        resolving to a concrete value would actively assert it on every
        create/update - including overriding a manual change made directly
        in Keycloak. `accessType` is the one exception: it's passed through
        as None too, but the server always resolves an unset one to
        confidential (Keycloak's own create-time default for an omitted
        access type is public, not confidential).
        """
        return OidcDesiredState(
            access_type=oidc.access_type,
            direct_access_grants_enabled=oidc.direct_access_grants_enabled,
            service_accounts_enabled=oidc.service_accounts_enabled,
            redirect_uris=oidc.redirect_uris,
            post_logout_redirect_uris=oidc.post_logout_redirect_uris,
            web_origins=oidc.web_origins,
            consent_required=oidc.consent_required,
            full_scope_allowed=oidc.full_scope_allowed,
            default_client_scopes=oidc.default_client_scopes,
            optional_client_scopes=oidc.optional_client_scopes,
        )

    def compile_desired_state(
        self, clients: list[ManagedSsoClientV1]
    ) -> list[ManagedSsoClientDesiredState]:
        """Compile desired state from App-Interface data.

        Derives the Keycloak client_id here rather than server-side, since
        the naming policy is an app-interface concept - see the client_id
        assignment below for the exact scheme.
        """
        desired: list[ManagedSsoClientDesiredState] = []
        for client in clients:
            keycloak_instance = KeycloakInstanceRef(
                url=client.keycloak_instance.url,
                initial_access_token=Secret(
                    secret_manager_url=client.keycloak_instance.initial_access_token.url
                    or self.secret_manager_url,
                    path=client.keycloak_instance.initial_access_token.path,
                    field=client.keycloak_instance.initial_access_token.field,
                    version=client.keycloak_instance.initial_access_token.version,
                ),
            )
            output = (
                Secret(secret_manager_url=self.secret_manager_url, path=client.output)
                if client.output
                else None
            )
            match client:
                case ManagedSsoClientOpenidConnectV1():
                    # OIDC clientId naming scheme: "<app.name>-<name>"
                    # (design doc's "Client naming" section).
                    client_id = f"{client.app.name}-{client.name}".lower()
                    oidc = self._compile_oidc(client.oidc)
                case _:
                    raise IntegrationError(
                        f"{client.app.name}/{client.name}: unsupported protocol "
                        f"{client.protocol!r}"
                    )
            desired.append(
                ManagedSsoClientDesiredState(
                    client_id=client_id,
                    description=client.description,
                    enabled=client.enabled if client.enabled is not None else True,
                    keycloak_instance=keycloak_instance,
                    oidc=oidc,
                    output=output,
                )
            )
        return desired

    async def reconcile(
        self,
        desired_clients: list[ManagedSsoClientDesiredState],
        dry_run: bool,
    ) -> ManagedSsoClientTaskResponse:
        """Send desired state to qontract-api and return the task response."""
        request = ManagedSsoClientReconcileRequest(
            desired_clients=desired_clients,
            dry_run=dry_run,
        )
        with self.log_api_exceptions():
            response = await reconcile_managed_sso_client(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        clients = self.get_managed_sso_clients(query_func=gqlapi.query)
        desired_clients = self.compile_desired_state(clients)

        if not desired_clients:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(desired_clients=desired_clients, dry_run=dry_run)

        if not dry_run:
            # In non-dry-run, the task runs asynchronously in the background.
            # The reconcile loop re-queues on the next schedule tick; deduplication
            # prevents overlapping tasks (see tasks.py deduplicated_task).
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url, result_type=ManagedSsoClientTaskResult
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            match action:
                case ManagedSsoClientActionCreate():
                    logging.info(f"create client {action.client_id}")
                case ManagedSsoClientActionUpdate():
                    logging.info(f"update client {action.client_id}")
                case ManagedSsoClientActionMoveTenantSecret():
                    logging.info(
                        f"move tenant secret for client {action.client_id} to "
                        f"{action.tenant_secret_path}"
                    )
                case ManagedSsoClientActionDelete():
                    logging.info(f"delete client {action.client_id}")

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(task_result.errors)} error(s): {errors_summary}"
            )
