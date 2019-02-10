import logging

import reconcile.gql as gql
import utils.ldap_client as ldap_client

from reconcile.aggregated_list import (AggregatedList,
                                       AggregatedDiffRunner)

USERS_QUERY = """
{
  user {
    path
    redhat_username
  }
}
"""


def fetch_current_state():
    gqlapi = gql.get_api()
    result = gqlapi.query(USERS_QUERY)

    state = AggregatedList()

    for user in result['user']:
        params = {
            'username': user['redhat_username']
        }

        item = {
            'path': user['path']
        }

        state.add(params, item)

    return state


def fetch_desired_state(current_state):
    # we use current_state to avoid searching the entire org

    state = AggregatedList()

    for param_hash in current_state.get_all_params_hash():
        list_item = current_state.get_by_params_hash(param_hash)
        params = list_item['params']
        username = params['username']
        if not (ldap_client.user_exists(username)):
            continue
        
        item = list_item['items'] 

        state.add(params, item)
    
    return state


class RunnerAction(object):
    def __init__(self, dry_run):
        self.dry_run = dry_run

    def delete_user(self):
        label = "delete_user"

        def action(params, items):
            username = params['username']

            for item in items:
                logging.info([label, username, item['path']])

            if not self.dry_run:
                pass

        return action


def run(dry_run=False):
    current_state = fetch_current_state()
    desired_state = fetch_desired_state(current_state)

    # calculate diff
    diff = current_state.diff(desired_state)

    # Run actions
    runner_action = RunnerAction(dry_run)
    runner = AggregatedDiffRunner(diff)

    runner.register("delete", runner_action.delete_user())

    runner.run()
