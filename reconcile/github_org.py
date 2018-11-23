import json
import sys
import logging
from github import Github

import reconcile.gql as gql
from reconcile.aggregated_list import AggregatedList, AggregatedDiffRunner
from reconcile.config import get_config

QUERY = """
{
  role {
    name
    members {
      ...on Bot {
        schema
        github_username_optional: github_username
      }
      ... on User {
        schema
        github_username
      }
    }
    permissions {
      service
      ...on PermissionGithubOrg {
        org
      }
      ...on PermissionGithubOrgTeam {
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
        g = Github(org_config["token"])
        org = g.get_organization(org_name)

        state.add(
            {
                'service': 'github-org',
                'org': org_name,
            },
            [member.login for member in org.get_members()]
        )

        for team in org.get_teams():
            state.add(
                {
                    'service': 'github-org-team',
                    'org': org_name,
                    'team': team.name
                },
                [member.login for member in team.get_members()]
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
            if permission['service'] in ['github-org', 'github-org-team']:
                state.add(permission, members)

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

    diff = current_state.diff(desired_state)

    if dry_run:
        print(json.dumps(diff, indent=4))
        sys.exit(0)

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
