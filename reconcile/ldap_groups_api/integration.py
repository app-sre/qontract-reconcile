"""ldap-groups-api client integration."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError
from qontract_api_client.client import ldap_groups as reconcile_ldap_groups
from qontract_api_client.schemas import (
    Group as ApiGroup,
)
from qontract_api_client.schemas import (
    InternalGroupsConnectionSecret,
    LdapGroupsReconcileRequest,
    LdapGroupsTaskResponse,
    LdapGroupsTaskResult,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError
from qontract_utils.internal_groups_api.models import Entity, EntityType

from reconcile.ldap_groups_api.models import (
    QONTRACT_INTEGRATION,
    LdapGroupMember,
    get_desired_groups_for_aws_roles,
    get_desired_groups_for_roles,
    get_integration_settings,
    get_roles,
    validate_no_circular_memberships,
)
from reconcile.utils import gql
from reconcile.utils.membershipsources.async_resolver import resolve_role_members
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.state import init_state

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.gql_definitions.ldap_groups.roles import RoleV1
    from reconcile.gql_definitions.ldap_groups.settings import LdapGroupsSettingsV1
    from reconcile.utils.state import State

LEGACY_INTEGRATION = "ldap-groups"


class LdapGroupsApiIntegrationParams(PydanticRunParams):
    aws_sso_namespace: str


class LdapGroupsApiIntegration(
    QontractReconcileApiIntegration[LdapGroupsApiIntegrationParams]
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        if not query_func:
            query_func = gql.get_api().query
        return {"roles": [c.model_dump() for c in get_roles(query_func)]}

    async def async_run(self, dry_run: bool) -> None:
        gql_api = gql.get_api()
        roles = get_roles(gql_api.query)
        if not roles:
            logging.debug("No roles found.")
            return

        settings = get_integration_settings(gql_api.query)
        secret = self.secret_reader.read_all_secret(settings.credentials)

        state_obj = init_state(integration=self.name, secret_reader=self.secret_reader)
        try:
            await self._run_reconcile(
                dry_run=dry_run,
                state_obj=state_obj,
                roles=roles,
                settings=settings,
                secret=secret,
            )
        finally:
            state_obj.cleanup()

    @staticmethod
    def _load_managed_groups(state_obj: State) -> list[str]:
        """Load managed groups, falling back to legacy ldap-groups state for cutover."""
        try:
            return sorted(state_obj["managed_groups"])
        except KeyError:
            pass
        legacy_key = f"state/{LEGACY_INTEGRATION}/managed_groups"
        try:
            resp = state_obj.client.get_object(Bucket=state_obj.bucket, Key=legacy_key)
            groups: list[str] = json.loads(resp["Body"].read())
            logging.info(
                "Inherited %d managed groups from legacy %s state",
                len(groups),
                LEGACY_INTEGRATION,
            )
            return sorted(groups)
        except ClientError, json.JSONDecodeError:
            return []

    async def _run_reconcile(
        self,
        dry_run: bool,
        state_obj: State,
        roles: list[RoleV1],
        settings: LdapGroupsSettingsV1,
        secret: dict[str, str],
    ) -> None:
        owner = Entity(
            type=EntityType.SERVICE_ACCOUNT,
            id=f"service-account-{secret['client_id']}",
        )

        resolved_members = await resolve_role_members(roles, user_cls=LdapGroupMember)

        desired_groups = get_desired_groups_for_roles(
            roles,
            contact_list=settings.contact_list,
            default_owners=[owner],
            resolved_members=resolved_members,
        ) + get_desired_groups_for_aws_roles(
            roles,
            contact_list=settings.contact_list,
            default_owners=[owner],
            aws_sso_namespace=self.params.aws_sso_namespace,
        )
        validate_no_circular_memberships(roles, desired_groups)

        managed_group_names = self._load_managed_groups(state_obj)

        connection = InternalGroupsConnectionSecret(
            secret_manager_url=self.secret_manager_url,
            path=settings.credentials.path,
            field=settings.credentials.field,
            version=settings.credentials.version,
            api_url=secret["api_url"],
            issuer_url=secret["issuer_url"],
            client_id=secret["client_id"],
        )

        # OpenAPI Group type differs from qontract_utils.Group; convert at the boundary.
        api_groups = [
            ApiGroup.model_validate(g.model_dump(by_alias=True)) for g in desired_groups
        ]

        request = LdapGroupsReconcileRequest(
            connection=connection,
            desired_groups=api_groups,
            managed_group_names=managed_group_names,
            dry_run=dry_run,
        )

        with self.log_api_exceptions():
            response: LdapGroupsTaskResponse = await reconcile_ldap_groups(request)
        logging.info(f"request_id: {response.id}")

        try:
            task_result = await self.poll_task_status(
                status_url=response.status_url, result_type=LdapGroupsTaskResult
            )
        except Exception:
            logging.exception(
                "Polling failed for task %s at %s. "
                "Preserving existing managed-groups bookmark.",
                response.id,
                response.status_url,
            )
            raise

        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "ldap-groups-api: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(f"{action.action_type=} {action.name=}")

        # Persist on FAILED as well as SUCCESS when the server returns partial state.
        # Do not persist on PENDING (poll timeout) or other non-terminal statuses.
        if (
            not dry_run
            and task_result.status in {TaskStatus.SUCCESS, TaskStatus.FAILED}
            and task_result.updated_managed_groups is not None
        ):
            state_obj["managed_groups"] = task_result.updated_managed_groups

        if errors_summary := "; ".join(task_result.errors or []):
            raise IntegrationError(
                f"ldap-groups-api: {len(task_result.errors)} error(s): {errors_summary}"
            )
