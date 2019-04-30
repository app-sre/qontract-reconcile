import logging
import os

import utils.raw_github_api
import utils.vault_client as vault_client
from utils.config import get_config
import utils.gql as gql


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


def run(dry_run):
    config = get_config()
    token = vault_client.read(
        config['github-repo-invites']['secret_path'],
        config['github-repo-invites']['secret_field'])

    g = utils.raw_github_api.RawGithubApi(token)

    gqlapi = gql.get_api()
    result = gqlapi.query(REPOS_QUERY)

    urls = []
    for app in result['apps_v1']:
        code_components = app['codeComponents']

        if code_components is None:
            continue

        for code_component in app['codeComponents']:
            if code_component['resource'] != 'upstream':
                continue
            urls.append(code_component['url'])

    for i in g.repo_invitations():
        invitation_id = i['id']
        invitation_url = i['html_url']

        url = os.path.dirname(invitation_url)

        if url in urls:
            logging.info(['accept', url])

            if not dry_run:
                g.accept_repo_invitation(invitation_id)
