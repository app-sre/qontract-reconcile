import logging

import reconcile.queries as queries

from reconcile.utils.unleash import get_feature_toggles
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State


QONTRACT_INTEGRATION = 'unleash-watcher'


def fetch_current_state(unleash_instance):
    api_url = f"{unleash_instance['url']}/api"
    secret_reader = SecretReader(settings=queries.get_app_interface_settings())
    admin_access_token = \
        secret_reader.read(unleash_instance['token'])
    return get_feature_toggles(api_url, admin_access_token)


def fetch_previous_state(state, instance_name):
    return state.get_all(instance_name)


def format_message(url, key, event,
                   previous_state=None, current_state=None):
    info = \
        ': {} -> {}'.format(previous_state,
                            current_state) \
        if previous_state and current_state else ''
    return '{} {} {}{}'.format(url, key, event, info)


def calculate_diff(current_state, previous_state):
    diffs = []

    for toggle, current_value in current_state.items():
        # new toggles
        if toggle not in previous_state:
            diff = {
                'event': 'created',
                'toggle': toggle,
                'to': current_value
            }
            diffs.append(diff)
        # updated toggles
        else:
            previous_value = previous_state[toggle]
            if current_value != previous_value:
                diff = {
                    'event': 'updated',
                    'toggle': toggle,
                    'from': previous_value,
                    'to': current_value
                }
                diffs.append(diff)

    # deleted toggles
    for toggle in previous_state:
        if toggle not in current_state:
            diff = {
                'event': 'deleted',
                'toggle': toggle
            }
            diffs.append(diff)

    return diffs


def init_slack_map(unleash_instance):
    settings = queries.get_app_interface_settings()
    slack_notifications = unleash_instance['notifications']['slack']
    slack_map = {}
    for slack_info in slack_notifications:
        workspace = slack_info['workspace']
        workspace_name = workspace['name']
        slack_integrations = workspace['integrations']
        slack_config = \
            [i for i in slack_integrations
             if i['name'] == QONTRACT_INTEGRATION]
        [slack_config] = slack_config

        token = slack_config['token']
        channel = slack_info['channel']
        icon_emoji = slack_info['icon_emoji']
        username = slack_info['username']

        slack = SlackApi(workspace_name,
                         token,
                         settings=settings,
                         init_usergroups=False,
                         channel=channel,
                         icon_emoji=icon_emoji,
                         username=username)

        slack_map[channel] = slack

    return slack_map


def act(dry_run, state, unleash_instance, diffs):
    if not dry_run and diffs:
        slack_notifications = \
            unleash_instance.get('notifications') \
            and unleash_instance['notifications'].get('slack')
        if not slack_notifications:
            return
        slack_map = init_slack_map(unleash_instance)

    for diff in reversed(diffs):
        event = diff['event']
        toggle = diff['toggle']

        msg = f"Feature toggle {toggle} {event}"
        if event == 'updated':
            msg += f": {diff['from']} -> {diff['to']}"
        logging.info(msg)
        if not dry_run:
            for slack in slack_map.values():
                slack.chat_post_message(msg)
            key = f"{unleash_instance['name']}/{toggle}"
            if event == 'created':
                state.add(key, diff['to'])
            elif event == 'deleted':
                state.rm(key)
            elif event == 'updated':
                state.add(key, diff['to'], force=True)


def run(dry_run):
    unleash_instances = queries.get_unleash_instances()
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )
    for unleash_instance in unleash_instances:
        instance_name = unleash_instance['name']
        current_state = fetch_current_state(unleash_instance)
        if not current_state:
            logging.warning(
                'not acting on empty Unleash instances. ' +
                'please create a feature toggle to get started.'
            )
            continue
        previous_state = fetch_previous_state(state, instance_name)
        diffs = calculate_diff(current_state, previous_state)
        if diffs:
            act(dry_run, state, unleash_instance, diffs)
