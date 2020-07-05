import os
import logging

from github import Github

import utils.gql as gql

from reconcile.github_org import get_config
from utils.raw_github_api import RawGithubApi


ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      github_username
    }
    bots {
      github_username
    }
    permissions {
      service
      ...on PermissionGithubOrg_v1 {
        org
        role
      }
      ...on PermissionGithubOrgTeam_v1 {
        org
        role
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'github-owners'


def fetch_desired_state():
    desired_state = {}
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    for role in roles:
        permissions = [p for p in role['permissions']
                       if p.get('service')
                       in ['github-org', 'github-org-team']
                       and p.get('role') == 'owner']
        if not permissions:
            continue
        for permission in permissions:
            github_org = permission['org']
            desired_state.setdefault(github_org, [])
            for user in role['users']:
                github_username = user['github_username']
                desired_state[github_org].append(github_username)
            for bot in role['bots']:
                github_username = bot['github_username']
                desired_state[github_org].append(github_username)

    return desired_state


def run(dry_run):
    base_url = os.environ.get('GITHUB_API', 'https://api.github.com')
    desired_state = fetch_desired_state()

    for github_org_name, desired_github_usernames in desired_state.items():
        config = get_config(desired_org_name=github_org_name)
        token = config['github'][github_org_name]['token']
        gh = Github(token, base_url=base_url)
        raw_gh = RawGithubApi(token)
        gh_org = gh.get_organization(github_org_name)
        gh_org_members = gh_org.get_members(role='admin')
        current_github_usernames = [m.login for m in gh_org_members]
        invitations = raw_gh.org_invitations(github_org_name)
        current_github_usernames.extend(invitations)
        for github_username in desired_github_usernames:
            if github_username not in current_github_usernames:
                logging.info(['add_owner', github_org_name, github_username])

                if not dry_run:
                    gh_user = gh.get_user(github_username)
                    gh_org.add_to_members(gh_user, 'admin')
