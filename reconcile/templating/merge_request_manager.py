import string
from typing import re

from pydantic import BaseModel

from reconcile.utils.vcs import VCS


PROMOTION_DATA_SEPARATOR = (
    "**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
TR_VERSION = "1.0.0"
TR_LABEL = "RENDERED"

VERSION_REF = "tr_version"
COLLECTION_REF = "provider"
TEMPLATE_HASH_REF = "template_hash"

COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
    for i in [
        VERSION_REF,
        COLLECTION_REF,
    ]
}

AVS_DESC = string.Template(
    f"""
This MR is triggered by app-interface's [template-rendering](https://github.com/app-sre/qontract-reconcile/blob/master/reconcile/templating/renderer.py).

Please **do not remove the {TR_LABEL} label** from this MR!

Parts of this description are used by the Template Renderer to manage the MR.

{PROMOTION_DATA_SEPARATOR}

* {VERSION_REF}: {TR_VERSION}
* {COLLECTION_REF}: $provider
"""
)



class TemplateInfo(BaseModel):
    collection: str
    template_hash: str

class ParserError(Exception):
    """Raised when some information cannot be found."""


class ParserVersionError(Exception):
    """Raised when the AVS version is outdated."""


class Parser:
    #TODO: Create base class for parser, to make it reusable
    """This class is only concerned with parsing an MR description rendered by the Renderer."""

    def _find_by_regex(self, pattern: re.Pattern, content: str) -> str:
        if matches := pattern.search(content):
            groups = matches.groups()
            if len(groups) == 1:
                return groups[0]

        raise ParserError(f"Could not find {pattern} in MR description")

    def _find_by_name(self, name: str, content: str) -> str:
        return self._find_by_regex(COMPILED_REGEXES[name], content)

    def parse(self, description: str) -> TemplateInfo:
        """Parse the description of an MR for AVS."""
        parts = description.split(PROMOTION_DATA_SEPARATOR)
        if not len(parts) == 2:
            raise ParserError("Could not find data separator in MR description")

        if TR_VERSION != self._find_by_name(VERSION_REF, parts[1]):
            raise ParserVersionError("Version is outdated")
        return TemplateInfo(
            collection=self._find_by_name(COLLECTION_REF, parts[1]),
            template_hash=self._find_by_name(TEMPLATE_HASH_REF, parts[1]),
        )


class MergeRequestManager:
    """
    Manager for AVS merge requests. This class
    is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs for external resources that have new versions.

    For each external resource, there are exist just one MR to update
    the version number in the App-Interface. Old or obsolete MRs are
    closed automatically.
    """

    def __init__(
        self, vcs: VCS, parser: Parser
    ):
        self._vcs = vcs
        self._parser = parser


