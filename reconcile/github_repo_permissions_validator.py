import itertools
import logging
import os
import sys


from github import Github
from github.GithubException import UnknownObjectException
from reconcile import queries

from reconcile.github_repo_invites import run as get_invitations
from reconcile.jenkins_job_builder import init_jjb
from reconcile.github_org import get_default_config
from reconcile.utils.jjb_client import JJB
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = "github-repo-permissions-validator"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def get_jobs(jjb: JJB):
    jobs = jjb.get_all_jobs(job_types=["gh-pr-check", "gh-build"])
    return itertools.chain.from_iterable(jobs.values())


def init_github():
    base_url = os.environ.get("GITHUB_API", "https://api.github.com")
    token = get_default_config()["token"]
    return Github(token, base_url=base_url)


def run(dry_run):
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    jjb: JJB = init_jjb(secret_reader)
    jobs = get_jobs(jjb)
    if not jobs:
        logging.error(f"no jobs found")
        sys.exit(1)

    gh = init_github()

    invitations = get_invitations(dry_run=True)

    error = False
    for job in jobs:
        repo_url = jjb.get_repo_url(job)
        repo_name = repo_url.rstrip("/").replace("https://github.com/", "")
        repo = gh.get_repo(repo_name)
        permissions = repo.permissions
        if not permissions.push and repo_url not in invitations:
            logging.error(f"missing write permissions for bot in repo {repo_url}")
            error = True

    if error:
        sys.exit(1)
