import logging
import re
import string

from gitlab.v4.objects import ProjectMergeRequest
from pydantic import BaseModel

from reconcile.templating.renderer import TemplateOutput
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr import MergeRequestBase
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

MR_DESC = string.Template(
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
    """Raised when the version is outdated."""


class Parser:
    # TODO: Create base class for parser, to make it reusable
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


def render_description(collection: str, template_hash: str) -> str:
    return MR_DESC.substitute(provider=collection, template_hash=template_hash)


def render_title(collection: str) -> str:
    return f'[auto] Rendered Templates for collection "{collection}"'


class OpenMergeRequest(BaseModel):
    raw: ProjectMergeRequest
    template_info: TemplateInfo


class TemplateRenderingMR(MergeRequestBase):
    name = "TemplateRendering"

    def __init__(
        self,
        title: str,
        description: str,
        content: list[TemplateOutput],
        labels: list[str],
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._content = content
        self.labels = labels

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        for content in self._content:
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=f"data{content.path}",
                commit_message="aws version sync",
                content=content.content,
            )


class MergeRequestManager:
    # TODO: Create base class for Merge Request Manager, to make it reusable
    """ """

    def __init__(self, vcs: VCS, parser: Parser):
        self._vcs = vcs
        self._parser = parser
        self._open_mrs: list[OpenMergeRequest] = []
        self._open_mrs_with_problems: list[OpenMergeRequest] = []

    def _merge_request_already_exists(
        self,
        collection: str,
    ) -> OpenMergeRequest | None:
        for mr in self._open_mrs:
            if mr.template_info.collection == collection:
                return mr

        return None

    def _fetch_avs_managed_open_merge_requests(self) -> list[ProjectMergeRequest]:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        return [mr for mr in all_open_mrs if TR_LABEL in mr.labels]

    def housekeeping(self) -> None:
        """
        Close bad MRs:
        - bad description format
        - wrong version
        - merge conflict

        --> if we update the template output, we automatically close
        old open MRs and replace them with new ones.
        """
        for mr in self._fetch_avs_managed_open_merge_requests():
            attrs = mr.attributes
            desc = attrs.get("description")
            has_conflicts = attrs.get("has_conflicts", False)
            if has_conflicts:
                logging.info(
                    "Merge-conflict detected. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of a merge-conflict."
                )
                continue
            try:
                template_info = self._parser.parse(description=desc)
            except ParserVersionError:
                logging.info(
                    "Old MR version detected! Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because it has an outdated integration version"
                )
                continue
            except ParserError:
                logging.info(
                    "Bad MR description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of bad description format."
                )
                continue

            self._open_mrs.append(OpenMergeRequest(raw=mr, template_info=template_info))

    def create_tr_merge_request(self, output: list[TemplateOutput]) -> None:
        collections = [o.input.collection for o in output if o.input]
        template_hashes = [o.input.template_hash for o in output if o.input]
        assert len(collections) == 1
        assert len(template_hashes) == 1
        collection = collections[0]
        template_hash = template_hashes[0]

        """Create a new MR with the rendered template."""
        if mr := self._merge_request_already_exists(collection):
            if mr.template_info.template_hash == template_hash:
                logging.info(
                    "MR already exists and has the same template hash. Skipping",
                )
            else:
                logging.info(
                    "Template hash changed. Closing it",
                )
                self._vcs.close_app_interface_mr(
                    mr.raw,
                    "Closing this MR because the template hash has changed.",
                )
            return None

        description = render_description(collection, template_hash)
        title = render_title(collection)

        logging.info("Opening MR for %s with hash (%s)", collection, template_hash)
        mr_labels = [TR_LABEL]

        self._vcs.open_app_interface_merge_request(
            mr=TemplateRenderingMR(
                title=title,
                description=description,
                content=output,
                labels=mr_labels,
            )
        )
