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


def get_project_file_path(io_dir, project):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, project + '.json')


def run(dry_run=False, io_dir='throughput/'):
    gqlapi = gql.get_api()
    jira_boards = gqlapi.query(QUERY)['jira_boards']
    for jira_board in jira_boards:
        jira = JiraClient(jira_board)
        issues = jira.get_issues()
        current_state = {issue.key: issue.fields.status.name
                         for issue in issues}
        project_file_path = get_project_file_path(io_dir, jira.project)

        try:
            if not dry_run:
                slack_info = jira_board['slack']
                slack = SlackApi(slack_info['token'])
                channel = slack_info['channel']
                icon_emoji = \
                    ':{}:'.format(slack_info.get('icon_emoji', 'jira'))
                username = slack_info.get('username', 'Jira')

            with open(project_file_path, 'r') as f:
                previous_state = json.load(f)
            logging.debug('[{}] previous state found'.format(jira.project))

            new_issues = [k for k in current_state
                          if k not in previous_state]
            for key in new_issues:
                msg = '{}/browse/{} created'.format(jira.server, key)
                logging.info(msg)
                if not dry_run:
                    slack.chat_post_message(msg, channel,
                                            icon_emoji, username)

            deleted_issues = [k for k in previous_state
                              if k not in current_state]
            for key in deleted_issues:
                msg = '{} deleted'.format(key)
                logging.info(msg)
                if not dry_run:
                    slack.chat_post_message(msg, channel,
                                            icon_emoji, username)

            updated_issues = [k for k, s in current_state.items()
                              if k in previous_state
                              and s != previous_state[k]]
            for key in updated_issues:
                msg = '{}/browse/{} status change: {} -> {}'.format(
                    jira.server, key,
                    previous_state[key], current_state[key])
                logging.info(msg)
                if not dry_run:
                    slack.chat_post_message(msg, channel,
                                            icon_emoji, username)

        except IOError:
            logging.debug(
                '[{}] previous state not found'.format(jira.project))
        finally:
            with open(project_file_path, 'w') as f:
                json.dump(current_state, f)
