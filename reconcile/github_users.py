import re
import logging

import utils.gql as gql
import utils.smtp_client as smtp_client

from reconcile.github_org import get_config
from reconcile.ldap_users import init_users as init_users_and_paths
from utils.gitlab_api import GitLabApi
from reconcile.queries import GITLAB_INSTANCES_QUERY

from github import Github
from github.GithubException import GithubException
from requests.exceptions import ReadTimeout
from multiprocessing.dummy import Pool as ThreadPool
from functools import partial
from utils.retry import retry


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


@retry(exceptions=(GithubException, ReadTimeout))
def get_user_company(user, github):
    gh_user = github.get_user(login=user['github_username'])
    return user['redhat_username'], gh_user.company


def get_users_to_delete(results):
    pattern = r'^.*[Rr]ed ?[Hh]at.*$'
    redhat_usernames_to_delete = [u for u, c in results
                                  if c is None
                                  or not re.search(pattern, c)]
    users_and_paths = init_users_and_paths()
    return [u for u in users_and_paths
            if u['username'] in redhat_usernames_to_delete]


def send_email_notification(user):
    msg_template = '''
Hello,

This is an automated message coming from App-Interface.

The App SRE team adheres to the OpenShift GitHub policy:
https://mojo.redhat.com/docs/DOC-1200784

Your GitHub profile does not comply with the following requirements:

- Company field should contain "Red Hat".


For any questions, please ping @app-sre-ic on #sd-app-sre in CoreOS Slack,
or mail us at sd-app-sre@redhat.com.

App-Interface repository: https://gitlab.cee.redhat.com/service/app-interface

'''
    to = user['username']
    subject = 'App-Interface compliance - GitHub profile'
    body = msg_template

    smtp_client.send_mail(to, subject, body)


def run(gitlab_project_id, dry_run=False, thread_pool_size=10,
        enable_deletion=False, send_mails=False):
    users = fetch_users()
    g = init_github()

    pool = ThreadPool(thread_pool_size)
    get_user_company_partial = partial(get_user_company, github=g)
    results = pool.map(get_user_company_partial, users)

    users_to_delete = get_users_to_delete(results)

    if not dry_run and enable_deletion:
        gqlapi = gql.get_api()
        # assuming a single GitLab instance for now
        instance = gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]
        gl = GitLabApi(instance, project_id=gitlab_project_id)

    for user in users_to_delete:
        username = user['username']
        paths = user['paths']
        logging.info(['delete_user', username])

        if not dry_run:
            if send_mails:
                send_email_notification(user)
            elif enable_deletion:
                gl.create_delete_user_mr(username, paths)
            else:
                msg = ('\'delete\' action is not enabled. '
                       'Please run the integration manually '
                       'with the \'--enable-deletion\' flag.')
                logging.warning(msg)
