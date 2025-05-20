import logging
import random
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from enum import IntFlag, auto
from typing import Any, TypedDict

from jira import JIRAError
from pydantic import BaseModel

from reconcile.gql_definitions.jira_permissions_validator.jira_boards_for_permissions_validator import (
    JiraBoardV1,
)
from reconcile.gql_definitions.jira_permissions_validator.jira_boards_for_permissions_validator import (
    query as query_jira_boards,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.jira_settings import get_jira_settings
from reconcile.typed_queries.jiralert_settings import get_jiralert_settings
from reconcile.utils import gql, metrics
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.jira_client import JiraClient, JiraWatcherSettings
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import State, init_state

QONTRACT_INTEGRATION = "jira-permissions-validator"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 2, 0)

NameToIdMap = dict[str, str]


class BaseMetric(BaseModel):
    """Base class for metrics"""

    jira_server: str
    board: str


class PermissionErrorCounter(BaseMetric, metrics.GaugeMetric):
    """Boards with permission errors."""

    @classmethod
    def name(cls) -> str:
        return "jira_permissions_validator_permission_error"


class ValidationError(IntFlag):
    CANT_CREATE_ISSUE = auto()
    CANT_TRANSITION_ISSUES = auto()
    INVALID_ISSUE_TYPE = auto()
    INVALID_ISSUE_STATE = auto()
    INVALID_ISSUE_FIELD = auto()
    INVALID_PRIORITY = auto()
    PERMISSION_ERROR = auto()
    PUBLIC_PROJECT_NO_SECURITY_LEVEL = auto()
    INVALID_COMPONENT = auto()
    PROJECT_ARCHIVED = auto()


CustomIssueFields = dict[str, dict[str, str]]


class RunnerParams(TypedDict):
    boards: list[JiraBoardV1]
    board_check_interval_sec: int
    dry_run: bool


class CacheSource(TypedDict):
    boards: list


def board_is_valid(
    jira: JiraClient,
    board: JiraBoardV1,
    default_issue_type: str,
    default_reopen_state: str,
    jira_server_priorities: NameToIdMap,
    public_projects: Iterable[str],
) -> tuple[ValidationError, CustomIssueFields]:
    error = ValidationError(0)
    custom_fields: CustomIssueFields = {}

    try:
        if jira.is_archived:
            logging.error(f"[{board.name}] project is archived")
            return ValidationError.PROJECT_ARCHIVED, custom_fields

        if not jira.can_create_issues():
            logging.error(f"[{board.name}] can not create issues in project")
            error |= ValidationError.CANT_CREATE_ISSUE

        if not jira.can_transition_issues():
            logging.error(
                f"[{board.name}] AppSRE Jira Bot user does not have the permission to change the issue status."
            )
            error |= ValidationError.CANT_TRANSITION_ISSUES

        components = jira.components()
        for escalation_policy in board.escalation_policies or []:
            jira_component = escalation_policy.channels.jira_component
            if jira_component and jira_component not in components:
                logging.error(
                    f"[{board.name}] escalation policy '{escalation_policy.name}' references a non existing Jira component "
                    f"'{jira_component}'. Valid components: {components}"
                )
                error |= ValidationError.INVALID_COMPONENT

        issue_type = board.issue_type or default_issue_type
        project_issue_type = jira.get_issue_type(issue_type)
        if not project_issue_type:
            project_issue_types_str = ", ".join(
                t.name for t in jira.project_issue_types()
            )
            logging.error(
                f"[{board.name}] '{issue_type}' is not a valid issue type in project. Valid issue types: {project_issue_types_str}"
            )
            error |= ValidationError.INVALID_ISSUE_TYPE

        if project_issue_type:
            # Check issue attributes
            if not project_issue_type.statuses:
                logging.error(
                    f"[{board.name}] '{issue_type}' doesn't have any status. Choose a different issue type."
                )
                error |= ValidationError.INVALID_ISSUE_TYPE

            reopen_state = board.issue_reopen_state or default_reopen_state
            if reopen_state.lower() not in [
                t.lower() for t in project_issue_type.statuses
            ]:
                logging.error(
                    f"[{board.name}] '{reopen_state}' is not a valid state in project. Valid states: {project_issue_type.statuses}"
                )
                error |= ValidationError.INVALID_ISSUE_STATE

            if board.issue_resolve_state and board.issue_resolve_state.lower() not in [
                t.lower() for t in project_issue_type.statuses
            ]:
                logging.error(
                    f"[{board.name}] '{board.issue_resolve_state}' is not a valid state in project. Valid states: {project_issue_type.statuses}"
                )
                error |= ValidationError.INVALID_ISSUE_STATE

            for field in board.issue_fields or []:
                project_issue_field = jira.project_issue_field(
                    issue_type_id=project_issue_type.id, field=field.name
                )
                if not project_issue_field:
                    logging.error(
                        f"[{board.name}] '{field.name}' is not a valid field for '{project_issue_type.name}' in this project."
                    )

                    error |= ValidationError.INVALID_ISSUE_FIELD
                    continue

                for option in project_issue_field.options:
                    if option == field.value:
                        # cache the field id and option value/name for later use, e.g. in jiralert templates
                        custom_fields[project_issue_field.id] = option.dict()
                        break
                else:
                    # field.value is not in the allowed options
                    logging.error(
                        f"[{board.name}] '{field.name}' has an invalid value '{field.value}'. Valid values: {project_issue_field.options}"
                    )
                    error |= ValidationError.INVALID_ISSUE_FIELD
                    continue

        if board.name in public_projects and "Security Level" not in [
            f.name for f in board.issue_fields or []
        ]:
            logging.error(
                f"[{board.name}] is a public project, but the security level is not defined. Please add 'Security Level' field to the issueFields!"
            )
            error |= ValidationError.PUBLIC_PROJECT_NO_SECURITY_LEVEL

        project_priorities = jira.project_priority_scheme()
        # get the priority names from the project priorities ids
        project_priorities_names = [
            p_name
            for project_p_id in project_priorities
            for p_name, p_id in jira_server_priorities.items()
            if p_id == project_p_id
        ]
        for priority in board.severity_priority_mappings.mappings:
            if priority.priority not in jira_server_priorities:
                logging.error(
                    f"[{board.name}] {priority.priority} is not a valid Jira priority. Valid priorities: {project_priorities_names}"
                )
                error |= ValidationError.INVALID_PRIORITY
                continue
            if jira_server_priorities[priority.priority] not in project_priorities:
                logging.error(
                    f"[{board.name}] {priority.priority} is not a valid priority in project. Valid priorities: {project_priorities_names}"
                )
                error |= ValidationError.INVALID_PRIORITY
    except JIRAError as e:
        if e.status_code == 401:
            # sporadic 401 errors, retrying
            logging.debug(f"[{board.name}] sporadic 401 error! Retry later.")
        elif e.status_code == 403:
            logging.error(
                f"[{board.name}] AppSRE Jira Bot user does not have all necessary permissions. Try granting the user the administrator permissions. API URL: {e.url}"
            )
            error |= ValidationError.PERMISSION_ERROR
        else:
            raise

    return error, custom_fields


def validate_boards(
    metrics_container: metrics.MetricsContainer,
    secret_reader: SecretReaderBase,
    jira_client_settings: JiraWatcherSettings | None,
    jira_boards: Sequence[JiraBoardV1],
    default_issue_type: str,
    default_reopen_state: str,
    board_check_interval_sec: int,
    dry_run: bool,
    state: State,
    jira_client_class: type[JiraClient] = JiraClient,
) -> bool:
    error = False
    jira_clients: dict[str, JiraClient] = {}
    for board in jira_boards:
        next_run_time = state.get(board.name, 0)
        if time.time() <= next_run_time:
            if not dry_run:
                # always skip for non-dry-run mode
                continue
            # dry-run mode
            elif len(jira_boards) > 1:
                logging.info(f"[{board.name}] Use cache results. Skipping ...")
                continue

        logging.debug(f"[{board.name}] checking ...")
        if board.server.server_url not in jira_clients:
            jira_clients[board.server.server_url] = jira_client_class.create(
                project_name=board.name,
                token=secret_reader.read_secret(board.server.token),
                server_url=board.server.server_url,
                jira_watcher_settings=jira_client_settings,
            )
        jira = jira_clients[board.server.server_url]
        jira.project = board.name
        try:
            error_flags, custom_fields = board_is_valid(
                jira=jira,
                board=board,
                default_issue_type=default_issue_type,
                default_reopen_state=default_reopen_state,
                jira_server_priorities={p.name: p.id for p in jira.priorities()},
                public_projects=jira.public_projects(),
            )
            match error_flags:
                case 0:
                    # no errors
                    logging.debug(f"[{board.name}] is valid")
                    if not dry_run:
                        # set the run time for the next check
                        state[board.name] = (
                            time.time()
                            + board_check_interval_sec
                            # add some randomness to avoid all boards checking at the same time
                            + random.randint(0, 3600)
                        )
                case ValidationError.PERMISSION_ERROR:
                    # we don't have all the permissions, but we can create jira tickets
                    metrics_container.set_gauge(
                        PermissionErrorCounter(
                            jira_server=board.server.server_url,
                            board=board.name,
                        ),
                        value=1,
                    )
                    if dry_run:
                        # throw an error for MR checks but not in prod mode
                        error = True
                case (
                    ValidationError.CANT_CREATE_ISSUE | ValidationError.PROJECT_ARCHIVED
                ):
                    if dry_run:
                        # throw an error for MR checks but not in prod mode
                        error = True
                case _:
                    error = True

            # cache the field ids for later use, e.g. in jiralert templates
            state[f"{board.name}-ids"] = custom_fields
        except Exception as e:
            logging.error(f"[{board.name}] {e}")
            error = True
    return error


def get_jira_boards(
    query_func: Callable,
    jira_board_names: list[str] | None = None,
) -> list[JiraBoardV1]:
    return [
        board
        for board in query_jira_boards(query_func=query_func).jira_boards or []
        if integration_is_enabled(QONTRACT_INTEGRATION, board)
        and (
            not jira_board_names
            or board.name.lower() in [name.lower() for name in jira_board_names]
        )
    ]


def export_boards(boards: list[JiraBoardV1]) -> list[dict]:
    return [board.dict() for board in boards]


@defer
def run(
    dry_run: bool,
    jira_board_name: list[str] | None = None,
    board_check_interval_sec: int = 3600,
    defer: Callable | None = None,
) -> None:
    gql_api = gql.get_api()
    boards = get_jira_boards(query_func=gql_api.query, jira_board_names=jira_board_name)
    settings = get_jira_settings(gql_api=gql_api)
    jiralert_settings = get_jiralert_settings(query_func=gql_api.query)
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    if defer:
        defer(state.cleanup)

    with metrics.transactional_metrics("jira-boards") as metrics_container:
        error = validate_boards(
            metrics_container=metrics_container,
            secret_reader=secret_reader,
            jira_client_settings=settings.jira_watcher,
            jira_boards=boards,
            default_issue_type=jiralert_settings.default_issue_type,
            default_reopen_state=jiralert_settings.default_reopen_state,
            board_check_interval_sec=board_check_interval_sec,
            dry_run=dry_run,
            state=state,
        )

    if error:
        sys.exit(ExitCodes.ERROR)


def early_exit_desired_state(
    *args: Any, jira_board_name: list[str] | None = None, **kwargs: Any
) -> dict[str, Any]:
    return {
        "boards": export_boards(
            get_jira_boards(
                query_func=gql.get_api().query,
                jira_board_names=jira_board_name,
            )
        )
    }


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="jira_board_name",
        shard_path_selectors={"boards[*].name"},
        shard_arg_is_collection=True,
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
