import os
import json
import logging

import reconcile.queries as queries

from utils.unleash import get_feature_toggles
from utils.slack_api import SlackApi
from utils import secret_reader


QONTRACT_INTEGRATION = 'unleash-watcher'


def fetch_current_state(unleash_instance):
    api_url = f"{unleash_instance['url']}/api"
    admin_access_token = \
        secret_reader.read(unleash_instance['token'],
        settings=queries.get_app_interface_settings())
    return get_feature_toggles(api_url, admin_access_token)


def get_project_file_path(io_dir, project):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, project + '.json')


def fetch_previous_state(io_dir, project):
    project_file_path = get_project_file_path(io_dir, project)
    try:
        with open(project_file_path, 'r') as f:
            logging.debug('[{}] previous state found'.format(project))
            return json.load(f)
    except IOError:
        logging.debug('[{}] previous state not found'.format(project))
        return None


def format_message(url, key, event,
                   previous_state=None, current_state=None):
    info = \
        ': {} -> {}'.format(previous_state,
                            current_state) \
        if previous_state and current_state else ''
    return '{} {} {}{}'.format(url, key, event, info)


def calculate_diff(server, current_state, previous_state):
    messages = []
    new_issues = [format_message(server, key, data, 'created')
                  for key in current_state
                  if key not in previous_state]
    messages.extend(new_issues)

    deleted_issues = [format_message(server, key, data, 'deleted')
                      for key in previous_state
                      if key not in current_state]
    messages.extend(deleted_issues)

    updated_issues = \
        [format_message(server, key, 'status change',
                        previous_state[key],
                        current_state[key])
         for key, data in current_state.items()
         if key in previous_state
         and data != previous_state[key]]
    messages.extend(updated_issues)

    return messages


def init_slack_map(unleash_instance):
    settings = queries.get_app_interface_settings()
    slack_notifications = unleash_instance['notifications']['slack']
    slack_map = {}
    for slack_info in slack_notifications:
        slack_integrations = slack_info['workspace']['integrations']
        slack_config = \
            [i for i in slack_integrations if i['name'] == QONTRACT_INTEGRATION]
        [slack_config] = slack_config

        token = slack_config['token']
        channel = slack_info['channel']
        icon_emoji = slack_info['icon_emoji']
        username = slack_info['username']

        slack = SlackApi(token,
                        settings=settings,
                        init_usergroups=False,
                        channel=channel,
                        icon_emoji=icon_emoji,
                        username=username)

        slack_map[channel] = slack

    return slack_map


def act(dry_run, unleash_instance, diffs):
    if not dry_run and diffs:
        slack_notifications = \
            unleash_instance.get('notifications') \
            and unleash_instance['notifications'].get('slack')
        if not slack_notifications:
            return
        slack_map = init_slack_map(unleash_instance)

    for diff in reversed(diffs):
        logging.info(diff)
        if not dry_run:
            for slack in slack_map.values():
                slack.chat_post_message(diff)


def write_state(io_dir, project, state):
    project_file_path = get_project_file_path(io_dir, project)
    with open(project_file_path, 'w') as f:
        json.dump(state, f)


def run(dry_run, io_dir='throughput/'):
    unleash_instances = queries.get_unleash_instances()
    for unleash_instance in unleash_instances:
        instance_name = unleash_instance['name']
        instance_url = unleash_instance['url']
        current_state = fetch_current_state(unleash_instance)
        previous_state = fetch_previous_state(io_dir, instance_name)
        if previous_state:
            diffs = calculate_diff(instance_url, current_state, previous_state)
            act(dry_run, unleash_instance, diffs)
        write_state(io_dir, instance_name, current_state)
