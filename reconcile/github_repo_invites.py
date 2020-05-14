import logging
import os

import utils.gql as gql
import utils.raw_github_api
import utils.secret_reader as secret_reader
import reconcile.queries as queries

from utils.config import get_config


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
    secret = {'path': config['secret_path'],
              'field': config['secret_field']}
    token = secret_reader.read(secret, settings=settings)
    g = utils.raw_github_api.RawGithubApi(token)

    urls = []
    for app in result['apps_v1']:
        code_components = app['codeComponents']

        if code_components is None:
            continue

        for code_component in app['codeComponents']:
            urls.append(code_component['url'])

    for i in g.repo_invitations():
        invitation_id = i['id']
        invitation_url = i['html_url']

        url = os.path.dirname(invitation_url)

        if url in urls:
            logging.info(['accept', url])

            if not dry_run:
                g.accept_repo_invitation(invitation_id)
        else:
            logging.debug(['skipping', url])
