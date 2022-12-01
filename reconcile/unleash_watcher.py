import logging

from reconcile import queries
from reconcile.slack_base import slackapi_from_slack_workspace
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.state import init_state
from reconcile.utils.unleash import get_feature_toggles

QONTRACT_INTEGRATION = "unleash-watcher"


def fetch_current_state(unleash_instance, secret_reader: SecretReader):
    api_url = f"{unleash_instance['url']}/api"
    admin_access_token = secret_reader.read(unleash_instance["token"])
    return get_feature_toggles(api_url, admin_access_token)


def fetch_previous_state(state, instance_name):
    return state.get_all(instance_name)


def format_message(url, key, event, previous_state=None, current_state=None):
    info = (
        ": {} -> {}".format(previous_state, current_state)
        if previous_state and current_state
        else ""
    )
    return "{} {} {}{}".format(url, key, event, info)


def calculate_diff(current_state, previous_state):
    diffs = []

    for toggle, current_value in current_state.items():
        # new toggles
        if toggle not in previous_state:
            diff = {"event": "created", "toggle": toggle, "to": current_value}
            diffs.append(diff)
        # updated toggles
        else:
            previous_value = previous_state[toggle]
            if current_value != previous_value:
                diff = {
                    "event": "updated",
                    "toggle": toggle,
                    "from": previous_value,
                    "to": current_value,
                }
                diffs.append(diff)

    # deleted toggles
    for toggle in previous_state:
        if toggle not in current_state:
            diff = {"event": "deleted", "toggle": toggle}
            diffs.append(diff)

    return diffs


def init_slack_map(
    unleash_instance, secret_reader: SecretReader
) -> dict[str, SlackApi]:
    return {
        slack_info["channel"]: slackapi_from_slack_workspace(
            slack_info, secret_reader, QONTRACT_INTEGRATION, init_usergroups=False
        )
        for slack_info in unleash_instance["notifications"]["slack"]
    }


def act(dry_run, state, unleash_instance, diffs, secret_reader: SecretReader):
    if not dry_run and diffs:
        slack_notifications = unleash_instance.get(
            "notifications"
        ) and unleash_instance["notifications"].get("slack")
        if not slack_notifications:
            return
        slack_map = init_slack_map(unleash_instance, secret_reader)

    for diff in reversed(diffs):
        event = diff["event"]
        toggle = diff["toggle"]

        msg = f"Feature toggle {toggle} {event}"
        if event == "updated":
            msg += f": {diff['from']} -> {diff['to']}"
        logging.info(msg)
        if not dry_run:
            for slack in slack_map.values():
                slack.chat_post_message(msg)
            key = f"{unleash_instance['name']}/{toggle}"
            if event == "created":
                state.add(key, diff["to"])
            elif event == "deleted":
                state.rm(key)
            elif event == "updated":
                state.add(key, diff["to"], force=True)


def run(dry_run):
    secret_reader = SecretReader(settings=queries.get_secret_reader_settings())
    unleash_instances = queries.get_unleash_instances()
    state = init_state(QONTRACT_INTEGRATION, secret_reader)
    for unleash_instance in unleash_instances:
        instance_name = unleash_instance["name"]
        current_state = fetch_current_state(unleash_instance, secret_reader)
        if not current_state:
            logging.warning(
                "not acting on empty Unleash instances. "
                + "please create a feature toggle to get started."
            )
            continue
        previous_state = fetch_previous_state(state, instance_name)
        diffs = calculate_diff(current_state, previous_state)
        if diffs:
            act(dry_run, state, unleash_instance, diffs, secret_reader)
