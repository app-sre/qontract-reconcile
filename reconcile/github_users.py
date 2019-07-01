import logging
from github import Github
from github.GithubObject import NotSet

import utils.gql as gql

from utils.aggregated_list import AggregatedList, AggregatedDiffRunner
from utils.config import get_config
from utils.raw_github_api import RawGithubApi

QUERY = """
{
  users: users_v1 {
    redhat_username
    github_username
  }
}
"""


def fetch_users():
    gqlapi = gql.get_api()
    return gqlapi.query(QUERY)['users']


def init_github():
    config = get_config()
    github_config = config['github']
    token = github_config['app-sre']['token']
    return Github(token)


def run(dry_run=False):
    users = fetch_users()
    g = init_github()
    for user in users:
        gh_user = g.get_user(login=user['github_username'])
        print(gh_user.company)
