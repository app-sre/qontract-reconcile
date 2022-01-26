from jira import JIRA
from http import HTTPStatus
import logging
from typing import Iterable

import requests

DEFAULT_CHECKPOINT_LABELS = ('sre-checkpoint')

def url_makes_sense(url: str) -> bool:
    """Guesses whether the URL may have a meaningful document.

    Obvious cases are if the document can be fully downloaded, but we
    also accept that the given document may require credentials that
    we don't have.

    The URL is non-sensical if the server is crashing, the document
    doesn't exist or the specified URL can't be even probed with GET.
    """
    rs = requests.get(url)
    # Codes above NOT_FOUND mean the URL to the document doesn't exist
    # or the URL is very malformed
    return (rs.status_code < HTTPStatus.NOT_FOUND)


def cut_ticket(jira: JIRA, project: str, parent: str,
               description: str, body: str,
               labels: Iterable[str] = DEFAULT_CHECKPOINT_LABELS) -> str:

    issue = jira.create_issue(
        project=project,
