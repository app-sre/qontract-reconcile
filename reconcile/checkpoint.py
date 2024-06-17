"""Performs an SRE checkpoint.

The checks are defined in
https://gitlab.cee.redhat.com/app-sre/contract/-/blob/master/content/process/sre_checkpoints.md

"""

import logging
import re
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from functools import (
    lru_cache,
    partial,
)
from http import HTTPStatus
from pathlib import Path
from typing import Any

import requests
from jinja2 import Template
from jira import Issue

from reconcile.utils.constants import PROJ_ROOT
from reconcile.utils.jira_client import JiraClient

DEFAULT_CHECKPOINT_LABELS = ("sre-checkpoint",)

# We reject the full RFC 5322 standard since many clients will choke
# with some carefully crafted valid addresses.
EMAIL_ADDRESS_REGEXP = re.compile(r"^\w+[-\w\.]*@(?:\w[-\w]*\w\.)+\w+")
MAX_EMAIL_ADDRESS_LENGTH = 320  # Per RFC3696

MISSING_DATA_TEMPLATE = PROJ_ROOT / "templates" / "jira-checkpoint-missinginfo.j2"


@lru_cache
def url_makes_sense(url: str) -> bool:
    """Guesses whether the URL may have a meaningful document.

    Obvious cases are if the document can be fully downloaded, but we
    also accept that the given document may require credentials that
    we don't have.

    The URL is non-sensical if the server is crashing, the document
    doesn't exist or the specified URL can't be even probed with GET.
    """
    url = url.strip()
    if not url:
        return False
    try:
        rs = requests.get(url, verify=False, timeout=60)
    except requests.exceptions.ConnectionError:
        return False
    # Codes above NOT_FOUND mean the URL to the document doesn't
    # exist, that the URL is very malformed or that it points to a
    # broken resource
    return rs.status_code < HTTPStatus.NOT_FOUND


def valid_owners(owners: Iterable[Mapping[str, str]]) -> bool:
    """Confirm whether all the owners have a name and a valid email address."""
    return all(
        o["name"]
        and o["email"]
        and EMAIL_ADDRESS_REGEXP.fullmatch(o["email"])
        and len(o["email"]) <= MAX_EMAIL_ADDRESS_LENGTH
        for o in owners
    )


VALIDATORS: dict[str, Callable] = {
    "sopsUrl": url_makes_sense,
    "architectureDocument": url_makes_sense,
    "grafanaUrls": lambda x: all(url_makes_sense(y["url"]) for y in x),
    "serviceOwners": valid_owners,
}


def render_template(
    template: Path, name: str, path: str, field: str, bad_value: str
) -> str:
    """Render the template with all its fields."""
    with open(template, encoding="locale") as f:
        t = Template(f.read(), keep_trailing_newline=True, trim_blocks=True)
        return t.render(
            app_name=name, app_path=path, field=field, field_value=bad_value
        )


def file_ticket(
    jira: JiraClient,
    field: str,
    app_name: str,
    app_path: str,
    labels: Iterable[str],
    parent: str,
    bad_value: str,
) -> Issue:
    """Return a ticket."""
    if bad_value:
        summary = f"Incorrect metadata {field} for {app_name}"
    else:
        summary = f"Missing metadata {field} for {app_name}"

    i = jira.create_issue(
        summary,
        render_template(MISSING_DATA_TEMPLATE, app_name, app_path, field, bad_value),
        labels=labels,
        links=(parent,),
    )
    return i


def report_invalid_metadata(
    app: Mapping[str, Any],
    path: str,
    board: Mapping[str, str | Mapping],
    settings: Mapping[str, Any],
    parent: str,
    dry_run: bool = False,
) -> None:
    """Cut tickets for any missing/invalid field in the app.

    During dry runs it will only log the rendered template.

    :param app: App description, as returned by
    queries.JIRA_BOARDS_QUICK_QUERY

    :param path: path in app-interface to said app

    :param board: JIRA board description, as per
    queries.JIRA_BOARDS_QUERY

    :param settings: app-interface settings (necessary to log into the
    JIRA instance)

    :param parent: parent ticket for this checkpoint

    :param dry_run: whether this is a dry run
    """
    if dry_run:
        do_cut = partial(
            render_template,
            template=MISSING_DATA_TEMPLATE,
            name=app["name"],
            path=path,
        )
    else:
        jira = JiraClient(board, settings)
        do_cut = partial(
            file_ticket,  # type: ignore
            jira=jira,
            app_name=app["name"],
            labels=DEFAULT_CHECKPOINT_LABELS,
            parent=parent,
            app_path=path,
        )

    for field, validator in VALIDATORS.items():
        value = app.get(field)
        try:
            if not validator(value):
                i = do_cut(field=field, bad_value=str(value))
                logging.error(f"Reporting bad field {field} with value {value}: {i}")
        except Exception as e:
            i = do_cut(field=field, bad_value=str(value))
            logging.error(f"Problems with {field} for {app['name']}: {e}")
            logging.error(f"Will report as {i}")
            logging.debug(f"Stack trace of {e}:", exc_info=True)
