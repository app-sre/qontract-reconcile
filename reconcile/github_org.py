import json
import logging
from github import Github
from github.GithubObject import NotSet

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

    def add_to_team(self):
        label = "add_to_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            if self.dry_run:
                for member in items:
                    logging.info([label, member, org, team])
            else:
                g = self.gh_api_store.github(org)
                gh_org = g.get_organization(org)
                teams = {team.name: team.id for team in gh_org.get_teams()}
                gh_team = gh_org.get_team(teams[team])

                for member in items:
                    logging.info([label, member, org, team])
                    gh_user = g.get_user(member)
                    gh_team.add_membership(gh_user, "member")

        return action

    def del_from_team(self):
        label = "del_from_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            if self.dry_run:
                for member in items:
                    logging.info([label, member, org, team])
            else:
                g = self.gh_api_store.github(org)
                gh_org = g.get_organization(org)
                teams = {team.name: team.id for team in gh_org.get_teams()}
                gh_team = gh_org.get_team(teams[team])

                for member in items:
                    logging.info([label, member, org, team])
                    gh_user = g.get_user(member)
                    gh_team.remove_membership(gh_user)

        return action

    def create_team(self):
        label = "create_team"

        def action(params, items):
            org = params["org"]
            team = params["team"]

            logging.info([label, org, team])

            if not self.dry_run:
                g = self.gh_api_store.github(org)
                gh_org = g.get_organization(org)

                repo_names = NotSet
                permission = NotSet
                privacy = "secret"

                gh_org.create_team(team, repo_names, permission, privacy)

        return action

    def add_to_org(self):
        label = "add_to_org"

        def action(params, items):
            org = params["org"]

            if self.dry_run:
                for member in items:
                    logging.info([label, member, org])
            else:
                g = self.gh_api_store.github(org)
                gh_org = g.get_organization(org)

                for member in items:
                    logging.info([label, member, org])
                    gh_user = g.get_user(member)
                    gh_org.add_to_members(gh_user, 'member')

        return action

    def del_from_org(self):
        label = "del_from_org"

        def action(params, items):
            org = params["org"]

            if self.dry_run:
                for member in items:
                    logging.info([label, member, org])
            else:
                g = self.gh_api_store.github(org)
                gh_org = g.get_organization(org)

                for member in items:
                    logging.info([label, member, org])

                    if not self.dry_run:
                        gh_user = g.get_user(member)
                        gh_org.remove_from_membership(gh_user)

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
        runner_action.raise_exception("Cannot create a Github Org"),
        service_is("github-org"),
    )

    # insert github-org-team
    runner.register(
        "insert",
        runner_action.create_team(),
        service_is("github-org-team"),
    )
    runner.register(
        "insert",
        runner_action.add_to_team(),
        service_is("github-org-team"),
    )

    # delete github-org
    runner.register(
        "delete",
        runner_action.raise_exception("Cannot delete a Github Org"),
        service_is("github-org"),
    )

    # delete github-org-team
    runner.register(
        "delete",
        runner_action.del_from_team(),
        service_is("github-org-team"),
    )

    # update-insert github-org
    runner.register(
        "update-insert",
        runner_action.add_to_org(),
        service_is("github-org"),
    )

    # update-insert github-org-team
    runner.register(
        "update-insert",
        runner_action.add_to_team(),
        service_is("github-org-team"),
    )

    # update-delete github-org
    runner.register(
        "update-delete",
        runner_action.del_from_org(),
        service_is("github-org"),
    )

    # update-delete github-org-team
    runner.register(
        "update-delete",
        runner_action.del_from_team(),
        service_is("github-org-team"),
    )

    runner.run()
