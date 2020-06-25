import os
import sys
import semver
import logging

from github import Github

from reconcile.jenkins_job_builder import init_jjb
from reconcile.github_org import get_config

QONTRACT_INTEGRATION = 'github-repo-permissions-validator'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def get_jobs(jjb, instance_name):
    pr_check_jobs = \
        jjb.get_all_jobs(
            job_types=['gh-pr-check'],
            instance_name=instance_name
    ).get(instance_name)

    return pr_check_jobs


def init_github(bot_token_org_name):
    base_url = os.environ.get('GITHUB_API', 'https://api.github.com')
    config = get_config(desired_org_name=bot_token_org_name)
    token = config['github'][bot_token_org_name]['token']
    return Github(token, base_url=base_url)


def run(dry_run, instance_name, bot_token_org_name):
    jjb = init_jjb()
    pr_check_jobs = get_jobs(jjb, instance_name)
    if not pr_check_jobs:
        logging.error(f'no jobs found for instance {instance_name}')
        sys.exit(1)

    gh = init_github(bot_token_org_name)

    error = False
    for job in pr_check_jobs:
        repo_url = jjb.get_repo_url(job)
        repo_name = repo_url.rstrip("/").replace('https://github.com/', '')
        repo = gh.get_repo(repo_name)
        permissions = repo.permissions
        if not permissions.push:
            logging.error(
                f'missing edit permissions for bot in repo {repo_url}')
            error = True

    if error:
        sys.exit(1)
