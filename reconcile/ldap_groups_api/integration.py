"""ldap-groups-api client integration."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

from botocore.exceptions import ClientError
from qontract_api_client.client import ldap_groups as reconcile_ldap_groups
from qontract_api_client.exceptions import APIException
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
from reconcile.typed_queries.ldap_settings import get_ldap_settings
from reconcile.utils import gql
from reconcile.utils.json import json_dumps
from reconcile.utils.membershipsources.async_resolver import resolve_role_members
from reconcile.utils.membershipsources.models import has_ldap_sources
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
PENDING_TASK_STATE_KEY = "pending_task"
# Max age before pending_task is treated as a lost Celery reference (not Celery result_expires).
PENDING_TASK_MAX_AGE = timedelta(hours=6)


class PendingTaskRef(TypedDict):
    id: str
    status_url: str
    submitted_at: NotRequired[str]


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
                query_func=gql_api.query,
            )
        finally:
            state_obj.cleanup()

    @staticmethod
    def _persist_managed_groups(state_obj: State, groups: list[str]) -> None:
        """Persist to ldap-groups-api state and the legacy ldap-groups S3 key."""
        state_obj["managed_groups"] = groups
        legacy_key = f"state/{LEGACY_INTEGRATION}/managed_groups"
        state_obj.client.put_object(
            Bucket=state_obj.bucket,
            Key=legacy_key,
            Body=json_dumps(groups),
        )

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
        except ClientError as err:
            code = err.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return []
            raise
        except json.JSONDecodeError:
            raise

    @staticmethod
    def _clear_pending_task(state_obj: State) -> None:
        if state_obj.exists(PENDING_TASK_STATE_KEY):
            state_obj.rm(PENDING_TASK_STATE_KEY)

    @staticmethod
    def _persist_pending_task(
        state_obj: State, response: LdapGroupsTaskResponse
    ) -> None:
        state_obj[PENDING_TASK_STATE_KEY] = PendingTaskRef(
            id=response.id,
            status_url=response.status_url,
            submitted_at=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _pending_task_stale_reason(pending: PendingTaskRef) -> str | None:
        raw = pending.get("submitted_at")
        if not raw:
            return "missing_submitted_at"
        submitted = datetime.fromisoformat(raw)
        if submitted.tzinfo is None:
            submitted = submitted.replace(tzinfo=UTC)
        if datetime.now(UTC) - submitted > PENDING_TASK_MAX_AGE:
            return f"older_than_{PENDING_TASK_MAX_AGE}"
        return None

    def _clear_lost_pending_task(
        self, state_obj: State, pending: PendingTaskRef, reason: str
    ) -> None:
        try:
            managed_count = len(state_obj["managed_groups"])
        except KeyError:
            managed_count = 0
        logging.warning(
            "Clearing lost ldap-groups-api Celery task %s (%s); "
            "managed_groups bookmark unchanged (%d groups in state)",
            pending["id"],
            reason,
            managed_count,
        )
        self._clear_pending_task(state_obj)

    async def _poll_recovery_task_result(
        self, pending: PendingTaskRef
    ) -> LdapGroupsTaskResult:
        """Non-blocking status probe, then blocking poll if still pending."""
        quick = await self.poll_task_status(
            status_url=pending["status_url"],
            result_type=LdapGroupsTaskResult,
            timeout=0,
        )
        if quick.status != TaskStatus.PENDING:
            return quick
        try:
            return await self.poll_task_status(
                status_url=pending["status_url"],
                result_type=LdapGroupsTaskResult,
            )
        except APIException as exc:
            if exc.response.status_code != 408:
                raise
            if self._pending_task_stale_reason(pending) is not None:
                raise
            raise IntegrationError(
                "ldap-groups-api: previous reconciliation task "
                f"{pending['id']} did not complete within the status poll timeout"
            ) from exc

    async def _recover_pending_task(self, state_obj: State, dry_run: bool) -> None:
        if dry_run:
            if state_obj.exists(PENDING_TASK_STATE_KEY):
                logging.warning(
                    "Skipping recovery of pending ldap-groups-api task in dry-run"
                )
            return
        try:
            pending: PendingTaskRef = state_obj[PENDING_TASK_STATE_KEY]
        except KeyError:
            return

        stale_reason = self._pending_task_stale_reason(pending)
        if stale_reason:
            if stale_reason == "missing_submitted_at":
                logging.warning(
                    "pending_task %s has no submitted_at; treating as lost",
                    pending["id"],
                )
            self._clear_lost_pending_task(state_obj, pending, stale_reason)
            return

        logging.info(
            "Recovering pending ldap-groups-api task %s from prior run",
            pending["id"],
        )
        task_result = await self._poll_recovery_task_result(pending)
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "ldap-groups-api: previous reconciliation task "
                f"{pending['id']} is still pending"
            )

        if task_result.updated_managed_groups is not None:
            self._persist_managed_groups(
                state_obj, list(task_result.updated_managed_groups)
            )
        self._clear_pending_task(state_obj)
        if errors_summary := "; ".join(task_result.errors or []):
            raise IntegrationError(
                f"ldap-groups-api: {len(task_result.errors)} error(s): {errors_summary}"
            )

    async def _run_reconcile(
        self,
        dry_run: bool,
        state_obj: State,
        roles: list[RoleV1],
        settings: LdapGroupsSettingsV1,
        secret: dict[str, str],
        query_func: Callable,
    ) -> None:
        await self._recover_pending_task(state_obj, dry_run)

        owner = Entity(
            type=EntityType.SERVICE_ACCOUNT,
            id=f"service-account-{secret['client_id']}",
        )

        ldap_settings = None
        if has_ldap_sources(roles):
            ldap_settings = await asyncio.to_thread(
                get_ldap_settings, query_func=query_func
            )

        resolved_roles = await resolve_role_members(
            roles,
            user_cls=LdapGroupMember,
            query_func=query_func,
            ldap_settings=ldap_settings,
            secret_manager_url=self.secret_manager_url
            if ldap_settings is not None
            else None,
        )

        desired_groups = get_desired_groups_for_roles(
            resolved_roles,
            contact_list=settings.contact_list,
            default_owners=[owner],
        ) + get_desired_groups_for_aws_roles(
            resolved_roles,
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

        if not dry_run:
            self._persist_pending_task(state_obj, response)

        try:
            task_result = await self.poll_task_status(
                status_url=response.status_url, result_type=LdapGroupsTaskResult
            )
        except Exception:
            logging.exception(
                "Polling failed for task %s at %s; pending_task retained",
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

        if not dry_run and task_result.updated_managed_groups is not None:
            self._persist_managed_groups(
                state_obj, list(task_result.updated_managed_groups)
            )

        if not dry_run:
            self._clear_pending_task(state_obj)

        if errors_summary := "; ".join(task_result.errors or []):
            raise IntegrationError(
                f"ldap-groups-api: {len(task_result.errors)} error(s): {errors_summary}"
            )
