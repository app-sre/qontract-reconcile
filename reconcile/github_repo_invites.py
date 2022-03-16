import logging
import os

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from reconcile.utils import gql
from reconcile.utils import raw_github_api
from reconcile.utils.secret_reader import SecretReader
from reconcile import queries


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

QONTRACT_INTEGRATION = "github-repo-invites"


@dataclass
class CodeComponents:
    urls: set[str]
    known_orgs: set[str]


def _parse_code_components(
    raw: Optional[Iterable[Mapping[str, Any]]]
) -> CodeComponents:
    urls = set()
    known_orgs = set()
    for app in raw or []:
        code_components = app["codeComponents"]

        if not code_components:
            continue

        for code_component in app["codeComponents"]:
            url = code_component["url"]
            urls.add(url)
            org = url[: url.rindex("/")]
            known_orgs.add(org)
    return CodeComponents(
        urls=urls,
        known_orgs=known_orgs,
    )


def _accept_invitations(
    github: raw_github_api.RawGithubApi, code_components: CodeComponents, dry_run: bool
) -> set[str]:
    accepted_invitations = set()
    urls = code_components.urls
    known_orgs = code_components.known_orgs
    for i in github.repo_invitations():
        invitation_id = i["id"]
        invitation_url = i["html_url"]

        url = os.path.dirname(invitation_url)

        accept = url in urls or any(url.startswith(org) for org in known_orgs)
        if accept:
            logging.info(["accept", url])
            accepted_invitations.add(url)

            if not dry_run:
                github.accept_repo_invitation(invitation_id)
        else:
            logging.debug(["skipping", url])
    return accepted_invitations


def run(dry_run):
    gqlapi = gql.get_api()
    result = gqlapi.query(REPOS_QUERY)
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    secret = settings["githubRepoInvites"]["credentials"]
    token = secret_reader.read(secret)
    g = raw_github_api.RawGithubApi(token)

    code_components = _parse_code_components(result["apps_v1"])
    accepted_invitations = _accept_invitations(g, code_components, dry_run)

    return accepted_invitations
