import logging

import utils.threaded as threaded
import utils.git_secrets as git_secrets
import reconcile.aws_support_cases_sos as aws_sos
import reconcile.queries as queries

from github.GithubException import UnknownObjectException

from utils.aws_api import AWSApi
from reconcile.github_users import init_github


def strip_repo_url(repo_url):
    return repo_url.rstrip('/').replace('.git', '')


def get_all_repos_to_scan(repos):
    logging.info('getting full list of repos')
    all_repos = []
    all_repos.extend([strip_repo_url(r) for r in repos])
    g = init_github()
    for r in repos:
        logging.debug('getting forks: {}'.format(r))
        repo_name = r.replace('https://github.com/', '')
        repo = g.get_repo(repo_name)
        forks = repo.get_forks()
        try:
            all_repos.extend([strip_repo_url(f.clone_url) for f in forks])
        except UnknownObjectException:
            logging.info('not found {}'.format(r))

    return all_repos


def run(dry_run=False, gitlab_project_id=None, thread_pool_size=10):
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    existing_keys = aws.get_users_keys()
    existing_keys_list = [key for user_key in existing_keys.values()
                          for keys in user_key.values() for key in keys]
    logging.info('found {} existing keys'.format(len(existing_keys_list)))

    app_int_github_repos = queries.get_repos(server='https://github.com')
    all_repos = get_all_repos_to_scan(app_int_github_repos)
    logging.info('about to scan {} repos'.format(len(all_repos)))

    results = threaded.run(git_secrets.scan_history, all_repos,
                           thread_pool_size,
                           existing_keys=existing_keys_list)
    all_leaked_keys = [key for keys in results for key in keys]

    deleted_keys = aws_sos.get_deleted_keys(accounts)
    keys_to_delete = \
        [{'account': account, 'key': key}
         for key in all_leaked_keys
         for account, user_keys in existing_keys.items()
         if key in [uk for uks in user_keys.values() for uk in uks]
         and key not in deleted_keys[account]]
    aws_sos.act(dry_run, gitlab_project_id, accounts, keys_to_delete)
