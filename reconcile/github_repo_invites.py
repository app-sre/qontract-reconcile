import logging
import os

import reconcile.utils.gql as gql
import reconcile.utils.raw_github_api as raw_github_api
from reconcile.utils.secret_reader import SecretReader
import reconcile.queries as queries

from reconcile.utils.config import get_config


REPOS_QUERY = """
{
    apps_v1 {
        codeComponents {
            url
            resource
        }
    }
}
"""

QONTRACT_INTEGRATION = 'github-repo-invites'


def run(dry_run):
    gqlapi = gql.get_api()
    result = gqlapi.query(REPOS_QUERY)
    config = get_config()['github-repo-invites']
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    secret = {'path': config['secret_path'],
              'field': config['secret_field']}
    token = secret_reader.read(secret)
    g = raw_github_api.RawGithubApi(token)

    urls = set()
    known_orgs = set()
    for app in result['apps_v1']:
        code_components = app['codeComponents']

        if code_components is None:
            continue

        for code_component in app['codeComponents']:
            url = code_component['url']
            urls.add(url)
            org = url[:url.rindex('/')]
            known_orgs.add(org)

    invitations = set()
    for i in g.repo_invitations():
        invitation_id = i['id']
        invitation_url = i['html_url']

        url = os.path.dirname(invitation_url)

        accept = url in urls or any(url.startswith(org) for org in known_orgs)
        if accept:
            logging.info(['accept', url])
            invitations.add(url)

            if not dry_run:
                g.accept_repo_invitation(invitation_id)
        else:
            logging.debug(['skipping', url])

    return invitations
