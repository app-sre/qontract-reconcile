import json
import sys
from github import Github

import reconcile.gql as gql
from reconcile.aggregated_list import AggregatedList
from reconcile.config import get_config

QUERY = """
{
  access {
    teams {
      members {
        github_username
      }
      permissions {
        service
        ...on AccessPermissionGithubOrg {
          org
        }
        ...on AccessPermissionGithubOrgTeam {
          org
          team
        }
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

    for datafile in result['data']['access']:
        for team in datafile['teams']:
            members = [i['github_username'] for i in team['members']]
            for params in team['permissions']:
                state.add(params, members)

    return state


def run(dry_run=False):
    config = get_config()

    current_state = fetch_current_state(config)
    desired_state = fetch_desired_state()

    if dry_run:
        print(json.dumps(current_state.diff(desired_state)))
        sys.exit(0)
