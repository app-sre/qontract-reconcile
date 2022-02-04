"""Performs an SRE checkpoint.

The checks are defined in
https://gitlab.cee.redhat.com/app-sre/contract/-/blob/master/content/process/sre_checkpoints.md

"""
from http import HTTPStatus
import logging
from typing import Iterable, Mapping, Optional
import re

import requests

from jinja2 import Template

from reconcile.utils.jira_client import JiraClient
from reconcile.utils.constants import PROJ_ROOT

from jira import Issue


DEFAULT_CHECKPOINT_LABELS = ('sre-checkpoint')

# We reject the full RFC 5322 standard since many clients will choke
# with some carefully crafted valid addresses. We might
EMAIL_ADDRESS_REGEXP = re.compile(r'^\w+[-\w\.]*@(?:\w[-\w]*\w\.)+\w+')
MAX_EMAIL_ADDRESS_LENGTH = 320  # Per RFC3696

MISSING_DATA_TEMPLATE = PROJ_ROOT / 'templates' / 'jira-checkpoint-missinginfo.j2'


def url_makes_sense(url: str) -> bool:
    """Guesses whether the URL may have a meaningful document.

    Obvious cases are if the document can be fully downloaded, but we
    also accept that the given document may require credentials that
    we don't have.

    The URL is non-sensical if the server is crashing, the document
    doesn't exist or the specified URL can't be even probed with GET.
    """
    rs = requests.get(url)
    # Codes above NOT_FOUND mean the URL to the document doesn't
    # exist, that the URL is very malformed or that it points to a
    # broken resource
    return (rs.status_code < HTTPStatus.NOT_FOUND)


def valid_owners(owners: Iterable[Mapping[str, str]]) -> bool:
    """Confirm whether all the owners have a name and a valid email address."""
    return all(o['name'] and o['email'] and
               EMAIL_ADDRESS_REGEXP.fullmatch(o['email'])
               and len(o['email']) <= MAX_EMAIL_ADDRESS_LENGTH
               for o in owners)


VALIDATORS = {
    'sopsUrl': url_makes_sense,
    'architectureDocument': url_makes_sense,
    'grafanaUrl': url_makes_sense,
    'serviceOwners': valid_owners,
}


def render_template(template: str, name: str, path: str, field: str, value: str) -> str:
    """Do stuff."""
    with open(template) as f:
        t = Template(f.read(),
                     keep_trailing_newline=True,
                     trim_blocks=True)
        return t.render(app_name=name,
                        app_path=path,
                        field=field,
                        field_value=value)


def file_ticket(jira: JiraClient, field: str, app_name: str,
                labels: Iterable[str], parent: str,
                bad_value: Optional[str]) -> Issue:
    """Return a ticket."""
    if bad_value:
        summary = f"Incorrect metadata {field} for {app_name}"
    else:
        summary = f"Missing metadata {field} for {app_name}"

    i = jira.create_issue(
        summary,
        render_template(MISSING_DATA_TEMPLATE, app_name, field),
        labels=labels,
        links=(parent)
    )
    return i


def report_invalid_metadata(app: Mapping[str, Mapping],
                            board: Mapping[str, str],
                            settings: Mapping) -> None:
    """Cut tickets for any missing/invalid field in the app."""
    jira = JiraClient(board, settings)
    for f, v in VALIDATORS.items():
        try:
            if not v(app[f]):
                i = file_ticket(
                    jira, f, app['name'], DEFAULT_CHECKPOINT_LABELS)
                logging.info(f"Opened task {i.key} for field {f}")
        except Exception:
            file_ticket(jira, f, app['name'], DEFAULT_CHECKPOINT_LABELS)
            logging.exception(f"Problems with {f} for {app['name']} - "
                              f"opened task {i.key}")
