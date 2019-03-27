import logging

import utils.gql as gql
import utils.vault_client as vault_client

from utils.quay_api import QuayApi
from utils.aggregated_list import (AggregatedList,
                                   AggregatedDiffRunner)

QUAY_ORG_CATALOG_QUERY = """
{
  quay_orgs: quay_orgs_v1 {
    name
    automationToken {
      path
      field
      format
    }
  }
}
"""

QUAY_REPOS_QUERY = """
{
  apps: apps_v1 {
    quayRepos {
      org {
        name
      }
      items {
        name
        description
        public
      }
    }
  }
}
"""


def fetch_current_state(quay_api_store):
    state = AggregatedList()

    for name, quay_api in quay_api_store.items():
        for repo in quay_api.list_images():
            params = {
                'org': name,
                'repo': repo['name']
            }

            public = repo['is_public']
            description = repo['description']

            if description is None:
                description = ''

            item = {
                'public': public,
                'description': description.strip()
            }

            state.add(params, item)

    return state


def fetch_desired_state():
    gqlapi = gql.get_api()
    result = gqlapi.query(QUAY_REPOS_QUERY)

    state = AggregatedList()

    for app in result['apps']:
        quay_repos = app.get('quayRepos')

        if quay_repos is None:
            continue

        for quay_repo in quay_repos:
            name = quay_repo['org']['name']
            for repo in quay_repo['items']:
                params = {
                    'org': name,
                    'repo': repo['name']
                }

                item = {
                    'public': repo['public'],
                    'description': repo['description'].strip()
                }

                state.add(params, item)

    return state


class RunnerAction(object):
    def __init__(self, dry_run, quay_api_store):
        self.dry_run = dry_run
        self.quay_api_store = quay_api_store

    def update_fields(self, current_state):
        def action(params, items):
            org = params["org"]
            repo = params["repo"]

            quay_api = self.quay_api_store[org]

            params_hash = {
                'org': org,
                'repo': repo
            }

            current_state.get(params_hash)
            cur_info = current_state.get(params_hash)['items'][0]

            try:
                cur_desc = cur_info['description'].strip()
            except AttributeError:
                # sometimes Quay returns None as the description
                cur_desc = ''

            cur_public = cur_info['public']

            public = items[0]['public']
            desc = items[0]['description'].strip()

            if cur_public != public:
                logging.info(['update_public', org, repo, public])

                if not self.dry_run:
                    if public:
                        quay_api.repo_make_public(repo)
                    else:
                        quay_api.repo_make_private(repo)

            if cur_desc != desc:
                logging.info(['update_desc', org, repo, desc])

                if not self.dry_run:
                    quay_api.repo_update_description(repo, desc)

        return action

    def create_repo(self):
        label = "create_repo"

        def action(params, items):
            org = params["org"]
            repo = params["repo"]
            description = items[0]["description"]
            public = items[0]["public"]

            logging.info([label, org, repo, description, public])

            if not self.dry_run:
                quay_api = self.quay_api_store[org]
                quay_api.repo_create(repo, description, public)

        return action

    def delete_repo(self):
        label = "delete_repo"

        def action(params, items):
            org = params["org"]
            repo = params["repo"]

            logging.info([label, org, repo])

            if not self.dry_run:
                quay_api = self.quay_api_store[org]
                quay_api.repo_delete(repo)

        return action


def get_quay_api_store():
    store = {}

    gqlapi = gql.get_api()
    result = gqlapi.query(QUAY_ORG_CATALOG_QUERY)

    for org_data in result['quay_orgs']:
        token_path = org_data['automationToken']['path']
        token_field = org_data['automationToken']['field']
        token = vault_client.read(token_path, token_field)

        name = org_data['name']

        store[name] = QuayApi(token, name)

    return store


def run(dry_run=False):
    quay_api_store = get_quay_api_store()

    current_state = fetch_current_state(quay_api_store)
    desired_state = fetch_desired_state()

    # calculate diff
    diff = current_state.diff(desired_state)

    # Verify that there are no repeated repo declarations
    for items in diff.values():
        for repo in items:
            assert len(repo['items']) == 1

    # Run actions
    runner_action = RunnerAction(dry_run, quay_api_store)
    runner = AggregatedDiffRunner(diff)

    runner.register("update-insert",
                    runner_action.update_fields(current_state))
    runner.register("insert", runner_action.create_repo())
    runner.register("delete", runner_action.delete_repo())

    runner.run()
