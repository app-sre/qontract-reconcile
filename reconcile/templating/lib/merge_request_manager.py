import logging
import re
import string

from pydantic import BaseModel

from reconcile.templating.lib.model import TemplateOutput, TemplateResult
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.merge_request_manager.parser import (
    Parser,
)
from reconcile.utils.mr import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS

DATA_SEPARATOR = (
    "**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
TR_VERSION = "1.0.0"
TR_LABEL = "template-output"

VERSION_REF = "tr_version"
COLLECTION_REF = "collection"
TEMPLATE_RESULT_HASH_REF = "result_hash"

COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
    for i in [
        VERSION_REF,
        COLLECTION_REF,
        TEMPLATE_RESULT_HASH_REF,
    ]
}

MR_DESC = string.Template(
    f"""
This MR is triggered by app-interface's [template-rendering](https://github.com/app-sre/qontract-reconcile/blob/master/reconcile/templating/renderer.py).

Please **do not remove the {TR_LABEL} label** from this MR!

Parts of this description are used by the Template Renderer to manage the MR.

{DATA_SEPARATOR}

* {VERSION_REF}: $version
* {COLLECTION_REF}: $collection
* {TEMPLATE_RESULT_HASH_REF}: $result_hash
"""
)


def create_parser() -> Parser:
    return Parser[TemplateInfo](
        klass=TemplateInfo,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=TR_VERSION,
        data_separator=DATA_SEPARATOR,
    )


def render_description(
    collection: str, result_hash: str, version: str = TR_VERSION
) -> str:
    return MR_DESC.substitute(
        collection=collection, result_hash=result_hash, version=version
    )


def render_title(collection: str) -> str:
    return f'[auto] Rendered Templates for collection "{collection}"'


class TemplateInfo(BaseModel):
    collection: str
    result_hash: str


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
            if content.is_new:
                gitlab_cli.create_file(
                    branch_name=self.branch,
                    file_path=f"data{content.path}",
                    commit_message="termplate rendering output",
                    content=content.content,
                )
            else:
                gitlab_cli.update_file(
                    branch_name=self.branch,
                    file_path=f"data{content.path}",
                    commit_message="termplate rendering output",
                    content=content.content,
                )


class MrData(BaseModel):
    result: TemplateResult
    auto_approved: bool


class MergeRequestManager(MergeRequestManagerBase[TemplateInfo]):
    def __init__(self, vcs: VCS, parser: Parser):
        super().__init__(vcs, parser, TR_LABEL)

    def create_merge_request(self, data: MrData) -> None:
        if not self._housekeeping_ran:
            self.housekeeping()

        result = data.result
        output = result.outputs
        collection = result.collection
        result_hash = result.calc_result_hash()
        additional_labels = result.labels

        """Create a new MR with the rendered template."""
        if mr := self._merge_request_already_exists({"collection": collection}):
            if mr.mr_info.result_hash == result_hash:
                logging.info(
                    "MR already exists and has the same result hash. Skipping: %s",
                    mr.raw.attributes.get("web_url", "NO_WEBURL"),
                )
                return None
            else:
                logging.info(
                    "Collection Hash changed. Closing: %s",
                    mr.raw.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr.raw,
                    "Closing this MR because the result hash has changed.",
                )

        description = render_description(collection, result_hash)
        title = render_title(collection)

        logging.info("Opening MR for %s with hash (%s)", collection, result_hash)
        mr_labels = [TR_LABEL]

        if data.auto_approved:
            mr_labels.append(AUTO_MERGE)

        if additional_labels:
            mr_labels.extend(additional_labels)

        self._vcs.open_app_interface_merge_request(
            mr=TemplateRenderingMR(
                title=title,
                description=description,
                content=output,
                labels=mr_labels,
            )
        )
