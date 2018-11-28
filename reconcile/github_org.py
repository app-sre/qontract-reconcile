import json
import sys
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


def fetch_current_state(config):
    state = AggregatedList()

    for org_name, org_config in config['github'].items():
        token = org_config["token"]
        raw_gh_api = RawGithubApi(token)

        g = Github(token)
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
        if m['schema'] == 'access/bot.yml':
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


def _raise(msg):
    def raiseException(params, items):
        raise Exception(msg)
    return raiseException


def add_org_team(params, items):
    logging.info(["add_org_team", params["org"], params["team"]])


def del_org_team(params, items):
    logging.info(["del_org_team", params["org"], params["team"]])


def add_users_org(params, items):
    for member in items:
        logging.info([
            "add_to_org",
            member,
            params["org"]
        ])


def del_users_org(params, items):
    # delete users
    for member in items:
        logging.info([
            "del_from_org",
            member,
            params["org"]
        ])


def add_users_org_team(params, items):
    for member in items:
        logging.info([
            "add_to_org_team",
            member,
            params["org"],
            params["team"]
        ])


def del_users_org_team(params, items):
    # delete users
    for member in items:
        logging.info([
            "del_from_org_team",
            member,
            params["org"],
            params["team"]
        ])


def service_is(service):
    return lambda p: p.get("service") == service


def run(dry_run=False):
    config = get_config()

    current_state = fetch_current_state(config)
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

    if dry_run:
        print(json.dumps(diff, indent=4))
        sys.exit(0)

    # Run actions
    runner = AggregatedDiffRunner(diff)

    # insert github-org
    runner.register(
        "insert",
        service_is("github-org"),
        _raise("Cannot create a Github Org")
    )

    # insert github-org-team
    runner.register("insert", service_is("github-org-team"), add_org_team)
    runner.register(
        "insert",
        service_is("github-org-team"),
        add_users_org_team
    )

    # delete github-org
    runner.register(
        "delete",
        service_is("github-org"),
        _raise("Cannot delete a Github Org")
    )

    # delete github-org-team
    runner.register(
        "delete",
        service_is("github-org-team"),
        del_users_org_team
    )
    # TODO: Do we want to enable this?
    # runner.register("delete", service_is("github-org-team"), del_org_team)

    # update-insert github-org
    runner.register("update-insert", service_is("github-org"), add_users_org)

    # update-insert github-org-team
    runner.register(
        "update-insert",
        service_is("github-org-team"),
        add_users_org_team
    )

    # update-delete github-org
    runner.register("update-delete", service_is("github-org"), del_users_org)

    # update-delete github-org-team
    runner.register(
        "update-delete",
        service_is("github-org-team"),
        del_users_org_team
    )

    runner.run()
