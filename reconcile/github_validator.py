import logging
import os
import sys

from github import Github

from reconcile import queries
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "github-validator"


def run(dry_run):
    base_url = os.environ.get("GITHUB_API", "https://api.github.com")
    orgs = queries.get_github_orgs()
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    error = False
    for org in orgs:
        org_name = org["name"]
        token = secret_reader.read(org["token"])
        gh = Github(token, base_url=base_url)
        gh_org = gh.get_organization(org_name)

        current_2fa = gh_org.two_factor_requirement_enabled
        desired_2fa = org["two_factor_authentication"] or False
        if current_2fa != desired_2fa:
            logging.error(f"2FA mismatch for {org_name}")
            error = True

    if error:
        sys.exit(1)
