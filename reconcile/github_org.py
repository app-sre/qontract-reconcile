import json
import logging
from github import Github

import reconcile.gql as gql
from reconcile.aggregated_list import AggregatedList, AggregatedDiffRunner
from reconcile.config import get_config
from reconcile.raw_github_api import RawGithubApi

QUERY = """
{
  role {
    name
    members {
      ...on Bot_v1 {
        schema
        github_username_optional: github_username
      }
      ... on User_v1 {
        schema
        github_username
      }
    }
    permissions {
      service
      ...on PermissionGithubOrg_v1 {
        org
      }
      ...on PermissionGithubOrgTeam_v1 {
        org
        team
      }
    }
  }
}
"""


def fetch_current_state(gh_api_store):
    state = AggregatedList()

    for org_name in gh_api_store.orgs():
        g = gh_api_store.github(org_name)
        raw_gh_api = gh_api_store.raw_github_api(org_name)

        org = g.get_organization(org_name)

        members = [member.login for member in org.get_members()]
        members.extend(raw_gh_api.org_invitations(org_name))

        state.add(
            {
                'service': 'github-org',
                'org': org_name,
            },
            members
        )

        for team in org.get_teams():
            members = [member.login for member in team.get_members()]
            members.extend(raw_gh_api.team_invitations(team.id))

            state.add(
                {
                    'service': 'github-org-team',
                    'org': org_name,
                    'team': team.name
                },
                members
            )

    return state


def fetch_desired_state():
    gqlapi = gql.get_api()
    result_json = gqlapi.query(QUERY)
    result = json.loads(result_json)

    state = AggregatedList()

    def username(m):
        if m['schema'] == 'access/bot-1.yml':
            return m.get('github_username_optional')
        else:
            return m['github_username']

    for role in result['data']['role']:
        members = [
            member for member in
            (username(m) for m in role['members'])
            if member is not None
        ]

        for permission in role['permissions']:
            if permission['service'] == 'github-org':
                state.add(permission, members)
            elif permission['service'] == 'github-org-team':
                state.add(permission, members)
                state.add({
                    'service': 'github-org',
                    'org': permission['org'],
                }, members)

    return state


class GHApiStore(object):
    _orgs = {}

    def __init__(self, config):
        for org_name, org_config in config['github'].items():
            token = org_config['token']
            self._orgs[org_name] = (Github(token), RawGithubApi(token))

    def orgs(self):
        return self._orgs.keys()

    def github(self, org_name):
        return self._orgs[org_name][0]

    def raw_github_api(self, org_name):
        return self._orgs[org_name][1]


class RunnerAction(object):
    def __init__(self, dry_run, gh_api_store):
        self.dry_run = dry_run
        self.gh_api_store = gh_api_store

    def add_users_org_team(self):
        def action(params, items):
            for member in items:
                logging.info([
                    "add_to_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])

        return action

    def del_users_org_team(self):
        def action(params, items):
            # delete users
            for member in items:
                logging.info([
                    "del_from_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])
        return action

    def add_org_team(self):
        def action(params, items):
            logging.info([
                "add_org_team",
                params["org"],
                params["team"]
            ])
        return action

    def del_org_team(self):
        def action(params, items):
            logging.info([
                "del_org_team",
                params["org"],
                params["team"]
            ])
        return action

    def add_users_org(self):
        def action(params, items):
            for member in items:
                logging.info([
                    "add_to_org",
                    member,
                    params["org"]
                ])
        return action

    def del_users_org(self):
        def action(params, items):
            # delete users
            for member in items:
                logging.info([
                    "del_from_org",
                    member,
                    params["org"]
                ])
        return action

    @staticmethod
    def raise_exception(msg):
        def raiseException(params, items):
            raise Exception(msg)
        return raiseException


def service_is(service):
    return lambda params: params.get("service") == service


def run(dry_run=False):
    config = get_config()
    gh_api_store = GHApiStore(config)

    current_state = fetch_current_state(gh_api_store)
    desired_state = fetch_desired_state()

    # Ensure current_state and desired_state match orgs
    current_orgs = set([
        item["params"]["org"]
        for item in current_state.dump()
    ])

    desired_orgs = set([
        item["params"]["org"]
        for item in desired_state.dump()
    ])

    assert current_orgs == desired_orgs, \
        "Current orgs don't match desired orgs"

    # Calculate diff
    diff = current_state.diff(desired_state)

    # Run actions
    runner_action = RunnerAction(dry_run, gh_api_store)
    runner = AggregatedDiffRunner(diff)

    # insert github-org
    runner.register(
        "insert",
        service_is("github-org"),
        runner_action.raise_exception("Cannot create a Github Org")
    )

    # insert github-org-team
    runner.register(
        "insert",
        service_is("github-org-team"),
        runner_action.add_org_team()
    )
    runner.register(
        "insert",
        service_is("github-org-team"),
        runner_action.add_users_org_team()
    )

    # delete github-org
    runner.register(
        "delete",
        service_is("github-org"),
        runner_action.raise_exception("Cannot delete a Github Org")
    )

    # delete github-org-team
    runner.register(
        "delete",
        service_is("github-org-team"),
        runner_action.del_users_org_team()
    )

    # update-insert github-org
    runner.register(
        "update-insert",
        service_is("github-org"),
        runner_action.add_users_org()
    )

    # update-insert github-org-team
    runner.register(
        "update-insert",
        service_is("github-org-team"),
        runner_action.add_users_org_team()
    )

    # update-delete github-org
    runner.register(
        "update-delete",
        service_is("github-org"),
        runner_action.del_users_org()
    )

    # update-delete github-org-team
    runner.register(
        "update-delete",
        service_is("github-org-team"),
        runner_action.del_users_org_team()
    )

    runner.run(dry_run)
