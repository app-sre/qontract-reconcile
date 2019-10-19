import logging

from git import Repo

import utils.gql as gql
import utils.git_secrets as git_secrets
import reconcile.gitlab_permissions as gitlab_permissions
import reconcile.aws_support_cases_sos as aws_sos

from utils.aws_api import AWSApi
from utils.gitlab_api import GitLabApi
from reconcile.queries import AWS_ACCOUNTS_QUERY
from reconcile.queries import GITLAB_INSTANCES_QUERY
from reconcile.github_users import init_github


def get_key_to_delete(err):
    return err


def get_all_repos_to_scan(repos):
    logging.info('getting full list of repos')
    all_repos = []
    all_repos.extend(repos)
    g = init_github()
    for r in repos:
        logging.debug('getting forks: {}'.format(r))
        repo_name = r.replace('https://github.com/', '')
        repo = g.get_repo(repo_name)
        forks = repo.get_forks()
        for f in forks or []:
            logging.debug('found fork: {}'.format(f.clone_url))
        all_repos.extend([f.clone_url for f in forks])
    return all_repos


def run(gitlab_project_id, dry_run=False, thread_pool_size=10):
    gqlapi = gql.get_api()
    app_int_github_repos = \
        gitlab_permissions.get_repos(gqlapi, server='https://github.com')
    all_repos = get_all_repos_to_scan(app_int_github_repos)
    logging.info('about to scan {} repos'.format(len(all_repos)))

    keys_to_delete = []
    for r in all_repos:
        ok, err = git_secrets.scan_history(r)
        if not ok:
            key_to_delete = get_key_to_delete(err)
            keys_to_delete.append(key_to_delete)
            print(key_to_delete)

    import sys
    sys.exit()


    # from here things will be a bit different
    # need to find which account holds a key to delete
    accounts = gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']
    aws = AWSApi(thread_pool_size, accounts)
    deleted_keys = aws_sos.get_deleted_keys(accounts)
    existing_keys = aws.get_users_keys()
    keys_to_delete_from_cases = get_keys_to_delete(aws_support_cases)
    keys_to_delete = [ktd for ktd in keys_to_delete_from_cases
                      if ktd['key'] not in deleted_keys[ktd['account']]
                      and ktd['key'] in existing_keys[ktd['account']]]

    if not dry_run and keys_to_delete:
        # assuming a single GitLab instance for now
        instance = gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]
        gl = GitLabApi(instance, project_id=gitlab_project_id)

    for k in keys_to_delete:
        account = k['account']
        key = k['key']
        logging.info(['delete_aws_access_key', account, key])
        if not dry_run:
            path = 'data' + \
                [a['path'] for a in accounts if a['name'] == account][0]
            gl.create_delete_aws_access_key_mr(account, path, key)
