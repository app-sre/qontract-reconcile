import os
import json
import logging

import utils.gql as gql

from utils.jira_client import JiraClient
from utils.slack_api import SlackApi


QUERY = """
{
  jira_boards: jira_boards_v1 {
    path
    name
    serverUrl
    token {
      path
    }
    slack {
      token {
        path
        field
      }
      channel
      icon_emoji
      username
    }
  }
}
"""

QONTRACT_INTEGRATION = 'jira-watcher'


def fetch_current_state(jira_board):
    jira = JiraClient(jira_board)
    issues = jira.get_issues()
    return jira, {issue.key: issue.fields.status.name for issue in issues}


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


def format_message(server, key, event,
                   previous_state=None, current_state=None):
    info = \
        ': {} -> {}'.format(previous_state, current_state) \
        if previous_state and current_state else ''
    url = '{}/browse/{}'.format(server, key) if event != 'deleted' else key
    return '{} {}{}'.format(url, event, info)


def calculate_diff(server, current_state, previous_state):
    messages = []
    new_issues = [format_message(server, key, 'created')
                  for key in current_state
                  if key not in previous_state]
    messages.extend(new_issues)

    deleted_issues = [format_message(server, key, 'deleted')
                      for key in previous_state
                      if key not in current_state]
    messages.extend(deleted_issues)

    updated_issues = \
        [format_message(server, key, 'status change',
                        previous_state[key],
                        current_state[key])
         for key, status in current_state.items()
         if key in previous_state and status != previous_state[key]]
    messages.extend(updated_issues)

    return messages


def init_slack(jira_board):
    slack_info = jira_board['slack']
    channel = slack_info['channel']
    icon_emoji = \
        ':{}:'.format(slack_info.get('icon_emoji', 'jira'))
    username = slack_info.get('username', 'Jira')
    slack = SlackApi(slack_info['token'],
                     channel=channel,
                     icon_emoji=icon_emoji,
                     username=username)

    return slack


def act(dry_run, jira_board, diffs):
    if not dry_run and diffs:
        slack = init_slack(jira_board)

    for diff in diffs:
        logging.info(diff)
        if not dry_run:
            slack.chat_post_message(diff)


def write_state(io_dir, project, state):
    project_file_path = get_project_file_path(io_dir, project)
    with open(project_file_path, 'w') as f:
        json.dump(state, f)


def run(dry_run=False, io_dir='throughput/'):
    gqlapi = gql.get_api()
    jira_boards = gqlapi.query(QUERY)['jira_boards']
    for jira_board in jira_boards:
        jira, current_state = fetch_current_state(jira_board)
        previous_state = fetch_previous_state(io_dir, jira.project)
        if previous_state:
            diffs = calculate_diff(jira.server, current_state, previous_state)
            act(dry_run, jira_board, diffs)
        write_state(io_dir, jira.project, current_state)
