import os
import logging

from github import Github
from sretoolbox.utils import retry

from reconcile.utils import gql
from reconcile.utils import expiration

from reconcile.github_org import get_config
from reconcile.utils.raw_github_api import RawGithubApi


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
    expirationDate
  }
}
"""

QONTRACT_INTEGRATION = "github-owners"


def fetch_desired_state():
    desired_state = {}
    gqlapi = gql.get_api()
    roles = expiration.filter(gqlapi.query(ROLES_QUERY)["roles"])
    for role in roles:
        permissions = [
            p
            for p in role["permissions"]
            if p.get("service") in ["github-org", "github-org-team"]
            and p.get("role") == "owner"
        ]
        if not permissions:
            continue
        for permission in permissions:
            github_org = permission["org"]
            desired_state.setdefault(github_org, [])
            for user in role["users"]:
                github_username = user["github_username"]
                desired_state[github_org].append(github_username)
            for bot in role["bots"]:
                github_username = bot["github_username"]
                desired_state[github_org].append(github_username)

    return desired_state


@retry()
def get_current_github_usernames(github_org_name, github, raw_github):
    gh_org = github.get_organization(github_org_name)
    gh_org_members = gh_org.get_members(role="admin")
    current_github_usernames = [m.login for m in gh_org_members]
    invitations = raw_github.org_invitations(github_org_name)
    current_github_usernames.extend(invitations)

    return gh_org, current_github_usernames


def run(dry_run):
    base_url = os.environ.get("GITHUB_API", "https://api.github.com")
    config = get_config()
    desired_state = fetch_desired_state()

    for github_org_name, desired_github_usernames in desired_state.items():
        token = config["github"][github_org_name]["token"]
        gh = Github(token, base_url=base_url)
        raw_gh = RawGithubApi(token)
        gh_org, current_github_usernames = get_current_github_usernames(
            github_org_name, gh, raw_gh
        )
        current_github_usernames = [m.lower() for m in current_github_usernames]
        desired_github_usernames = [m.lower() for m in desired_github_usernames]
        for github_username in desired_github_usernames:
            if github_username not in current_github_usernames:
                logging.info(["add_owner", github_org_name, github_username])

                if not dry_run:
                    gh_user = gh.get_user(github_username)
                    gh_org.add_to_members(gh_user, "admin")
