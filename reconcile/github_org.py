import json
import sys
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

    for role in result['data']['role']:
        members = []
        for member in role['members']:
            if member['schema'] == 'access/bot.yml':
                if member.get('github_username_optional'):
                    members.append(member.get('github_username_optional'))
            elif member['schema'] == 'access/user.yml':
                members.append(member['github_username'])

        for permission in role['permissions']:
            service = permission['service']

            if service == 'github-org' or service == 'github-org-team':
                state.add(permission, members)

    return state


def run(dry_run=False):
    config = get_config()

    current_state = fetch_current_state(config)
    desired_state = fetch_desired_state()

    if dry_run:
        print(json.dumps(current_state.diff(desired_state)))
        sys.exit(0)
