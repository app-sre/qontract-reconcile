import logging

import utils.gql as gql
from utils.secret_reader import SecretReader
import reconcile.queries as queries

from utils.quay_api import QuayApi


QUAY_REPOS_QUERY = """
{
  apps: apps_v1 {
    name
    quayRepos {
      org {
        name
        automationToken {
          path
          field
        }
      }
      teams {
        permissions {
          service
          ... on PermissionGithubOrgTeam_v1 {
            org
            team
          }
        }
        role
      }
      items {
        name
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'quay-permissions'


def get_quay_api_store():
    quay_orgs = queries.get_quay_orgs()
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    store = {}
    for org_data in quay_orgs:
        name = org_data['name']
        server_url = org_data.get('serverUrl')
        token = secret_reader.read(org_data['automationToken'])
        store[name] = QuayApi(token, name, base_url=server_url)

    return store


def run(dry_run):
    gqlapi = gql.get_api()
    apps = gqlapi.query(QUAY_REPOS_QUERY)['apps']
    quay_api_store = get_quay_api_store()
    for app in apps:
        quay_repo_configs = app.get('quayRepos')
        if not quay_repo_configs:
            continue
        for quay_repo_config in quay_repo_configs:
            org_name = quay_repo_config['org']['name']
            quay_api = quay_api_store[org_name]
            teams = quay_repo_config.get('teams')
            if not teams:
                continue
            repos = quay_repo_config['items']
            for repo in repos:
                repo_name = repo['name']
                for team in teams:
                    permissions = team['permissions']
                    role = team['role']
                    for permission in permissions:
                        if permission['service'] != 'quay-membership':
                            logging.warning('wrong service kind, ' +
                                            'should be quay-membership')
                            continue
                        if permission['org'] != org_name:
                            logging.warning('wrong org, ' +
                                            f'should be {org_name}')
                            continue
                        team_name = permission['team']
                        current_role = \
                            quay_api.get_repo_team_permissions(
                                repo_name, team_name)
                        if current_role != role:
                            logging.info(
                                ['update_role', org_name, repo_name,
                                 team_name, role])
                            if not dry_run:
                                quay_api.set_repo_team_permissions(
                                    repo_name, team_name, role)
