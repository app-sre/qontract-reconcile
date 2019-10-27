import re
import logging

import utils.gql as gql
import utils.threaded as threaded
import utils.smtp_client as smtp_client
import reconcile.queries as queries
import reconcile.pull_request_gateway as prg

from reconcile.github_org import get_config
from reconcile.ldap_users import init_users as init_users_and_paths

from github import Github
from github.GithubException import GithubException
from requests.exceptions import ReadTimeout
from utils.retry import retry


QUERY = """
{
  users: users_v1 {
    org_username
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
    return user['org_username'], gh_user.company


def get_users_to_delete(results):
    pattern = r'^.*[Rr]ed ?[Hh]at.*$'
    org_usernames_to_delete = [u for u, c in results
                               if c is None
                               or not re.search(pattern, c)]
    users_and_paths = init_users_and_paths()
    return [u for u in users_and_paths
            if u['username'] in org_usernames_to_delete]


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

    results = threaded.run(get_user_company, users, thread_pool_size,
                           github=g)

    users_to_delete = get_users_to_delete(results)

    if not dry_run and enable_deletion:
        settings = queries.get_app_interface_settings()
        gw = prg.init(settings, gitlab_project_id)

    for user in users_to_delete:
        username = user['username']
        paths = user['paths']
        logging.info(['delete_user', username])

        if not dry_run:
            if send_mails:
                send_email_notification(user)
            elif enable_deletion:
                gw.create_delete_user_mr(username, paths)
            else:
                msg = ('\'delete\' action is not enabled. '
                       'Please run the integration manually '
                       'with the \'--enable-deletion\' flag.')
                logging.warning(msg)
