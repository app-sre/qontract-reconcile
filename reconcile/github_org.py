import json
import sys
import logging
from github import Github

import reconcile.gql as gql
from reconcile.aggregated_list import AggregatedList
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


def run(dry_run=False):
    config = get_config()

    current_state = fetch_current_state(config)
    desired_state = fetch_desired_state()

    actions = current_state.diff(desired_state)

    if dry_run:
        print(json.dumps(actions, indent=4))
        sys.exit(0)

    for item in actions["insert"]:
        params = item["params"]
        service = params["service"]

        if service == "github-org":
            raise Exception("Cannot create a Github Org")
        elif service == "github-org-team":
            # create team
            logging.info(["create_org_team", params["org"], params["team"]])

            # add users
            for member in item["items"]:
                logging.info([
                    "add_to_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])
        else:
            raise Exception("Unknown service: {}".format(service))

    for item in actions["delete"]:
        params = item["params"]
        service = params["service"]

        if service == "github-org":
            raise Exception("Cannot delete a Github Org")
        elif service == "github-org-team":
            # remove users
            for member in item["items"]:
                logging.info([
                    "delete_from_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])
            # TODO: Do we want to delete the team?
            # logging.info(["delete_org_team", params["org"], params["team"]])
        else:
            raise Exception("Unknown service: {}".format(service))

    for item in actions["update"]:
        params = item["params"]
        service = params["service"]

        if service == "github-org":
            for member in item["insert"]:
                logging.info(["add_to_org", member, params["org"]])

            for member in item["delete"]:
                logging.info(["remove_from_org", member, params["org"]])

        elif service == "github-org-team":
            for member in item["insert"]:
                logging.info([
                    "add_to_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])

            for member in item["delete"]:
                logging.info([
                    "remove_from_org_team",
                    member,
                    params["org"],
                    params["team"]
                ])
        else:
            raise Exception("Unknown service: {}".format(service))
