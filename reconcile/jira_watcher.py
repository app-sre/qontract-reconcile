import logging

from reconcile import queries
from reconcile.slack_base import slackapi_from_slack_workspace
from reconcile.utils.jira_client import JiraClient
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.sharding import is_in_shard_round_robin
from reconcile.utils.state import State

QONTRACT_INTEGRATION = "jira-watcher"


def fetch_current_state(jira_board, settings):
    jira = JiraClient(jira_board, settings=settings)
    issues = jira.get_issues(fields=["key", "status", "summary"])
    return jira, {
        issue.key: {"status": issue.fields.status.name, "summary": issue.fields.summary}
        for issue in issues
    }


def fetch_previous_state(state, project):
    return state.get(project, {})


def format_message(server, key, data, event, previous_state=None, current_state=None):
    summary = data["summary"]
    info = (
        ": {} -> {}".format(previous_state["status"], current_state["status"])
        if previous_state and current_state
        else ""
    )
    url = "{}/browse/{}".format(server, key)
    return "{} ({}) {}{}".format(url, summary, event, info)


def calculate_diff(server, current_state, previous_state):
    messages = []
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


def init_slack(jira_board):
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    slack_info = jira_board["slack"]

    return slackapi_from_slack_workspace(
        slack_info,
        secret_reader,
        QONTRACT_INTEGRATION,
        channel=slack_info.get("channel"),
        init_usergroups=False,
    )


def act(dry_run, jira_board, diffs):
    if not dry_run and diffs:
        slack = init_slack(jira_board)

    for diff in reversed(diffs):
        logging.info(diff)
        if not dry_run:
            slack.chat_post_message(diff)


def write_state(state, project, state_to_write):
    state.add(project, value=state_to_write, force=True)


def run(dry_run):
    jira_boards = [j for j in queries.get_jira_boards() if j.get("slack")]
    accounts = queries.get_state_aws_accounts()
    settings = queries.get_app_interface_settings()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    for index, jira_board in enumerate(jira_boards):
        if not is_in_shard_round_robin(jira_board["name"], index):
            continue
        jira, current_state = fetch_current_state(jira_board, settings)
        if not current_state:
            logging.warning(
                "not acting on empty Jira boards. "
                + "please create a ticket to get started."
            )
            continue
        previous_state = fetch_previous_state(state, jira.project)
        if previous_state:
            diffs = calculate_diff(jira.server, current_state, previous_state)
            act(dry_run, jira_board, diffs)
        if not dry_run:
            write_state(state, jira.project, current_state)
