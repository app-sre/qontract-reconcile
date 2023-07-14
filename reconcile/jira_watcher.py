import logging
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Optional

from reconcile.gql_definitions.common.jira_settings import AppInterfaceSettingsV1
from reconcile.gql_definitions.jira_watcher.jira_watcher_boards import (
    JiraBoardV1,
    SlackOutputV1,
)
from reconcile.gql_definitions.jira_watcher.jira_watcher_boards import (
    query as query_jira_boards,
)
from reconcile.slack_base import (
    SlackApi,
    slackapi_from_slack_workspace,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.jira_settings import get_jira_settings
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.jira_client import JiraClient
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.sharding import is_in_shard_round_robin
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "jira-watcher"


def fetch_current_state(
    jira_board: JiraBoardV1,
    settings: AppInterfaceSettingsV1,
    secret_reader: SecretReaderBase,
) -> tuple[JiraClient, dict[str, dict]]:
    token = secret_reader.read_secret(jira_board.server.token)
    jira = JiraClient.create(
        project_name=jira_board.name,
        token=token,
        server_url=jira_board.server.server_url,
        jira_watcher_settings=settings.jira_watcher,
    )
    issues = jira.get_issues(fields=["key", "status", "summary"])
    return jira, {
        issue.key: {"status": issue.fields.status.name, "summary": issue.fields.summary}
        for issue in issues
    }


def fetch_previous_state(state: State, project: str) -> dict[str, dict]:
    return state.get(project, {})


def format_message(
    server: str,
    key: str,
    data: Mapping,
    event: str,
    previous_state: Optional[Mapping] = None,
    current_state: Optional[Mapping] = None,
) -> str:
    summary = data["summary"]
    info = (
        ": {} -> {}".format(previous_state["status"], current_state["status"])
        if previous_state and current_state
        else ""
    )
    url = "{}/browse/{}".format(server, key)
    return "{} ({}) {}{}".format(url, summary, event, info)


def calculate_diff(
    server: str,
    current_state: Mapping[str, Mapping],
    previous_state: Mapping[str, Mapping],
) -> list[str]:
    messages: list[str] = []
    new_issues = [
        format_message(server, key, data, "created")
        for key, data in current_state.items()
        if key not in previous_state
    ]
    messages.extend(new_issues)

    deleted_issues = [
        format_message(server, key, data, "deleted")
        for key, data in previous_state.items()
        if key not in current_state
    ]
    messages.extend(deleted_issues)

    updated_issues = [
        format_message(
            server, key, data, "status change", previous_state[key], current_state[key]
        )
        for key, data in current_state.items()
        if key in previous_state and data["status"] != previous_state[key]["status"]
    ]
    messages.extend(updated_issues)

    return messages


def init_slack(slack: SlackOutputV1, secret_reader: SecretReaderBase) -> SlackApi:
    return slackapi_from_slack_workspace(
        slack.dict(by_alias=True),
        secret_reader,
        QONTRACT_INTEGRATION,
        channel=slack.channel,
        init_usergroups=False,
    )


def act(
    dry_run: bool,
    slack: SlackOutputV1,
    diffs: Iterable[str],
    secret_reader: SecretReaderBase,
) -> None:
    slack_api: Optional[SlackApi] = None
    if not dry_run and diffs:
        slack_api = init_slack(slack=slack, secret_reader=secret_reader)

    for diff in reversed(list(diffs)):
        logging.info(diff)
        if not dry_run:
            if not slack_api:
                raise RuntimeError("Slack API not initialized")
            slack_api.chat_post_message(diff)


def write_state(
    state: State, project: str, state_to_write: Mapping[str, Mapping]
) -> None:
    state.add(project, value=state_to_write, force=True)


@defer
def run(dry_run: bool, defer: Optional[Callable]) -> None:
    gql_api = gql.get_api()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    jira_boards = query_jira_boards(query_func=gql_api.query).jira_boards or []
    settings = get_jira_settings(gql_api=gql_api)
    state = init_state(integration=QONTRACT_INTEGRATION)
    if defer:
        defer(state.cleanup)
    for index, jira_board in enumerate(jira_boards):
        if not jira_board.slack:
            continue
        if not is_in_shard_round_robin(jira_board.name, index):
            continue
        jira, current_state = fetch_current_state(
            jira_board=jira_board, settings=settings, secret_reader=secret_reader
        )
        if not current_state:
            logging.warning(
                "not acting on empty Jira boards. "
                + "please create a ticket to get started."
            )
            continue
        previous_state = fetch_previous_state(state=state, project=jira.project)
        if previous_state:
            diffs = calculate_diff(
                jira_board.server.server_url, current_state, previous_state
            )
            act(
                dry_run=dry_run,
                slack=jira_board.slack,
                diffs=diffs,
                secret_reader=secret_reader,
            )
        if not dry_run:
            write_state(state, jira.project, current_state)
