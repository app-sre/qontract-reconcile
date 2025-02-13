import logging

from gitlab.exceptions import GitlabGetError
from pydantic import BaseModel

from reconcile.terraform_init.merge_request import (
    LABEL,
    Info,
    Renderer,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS


class TerraformInitMR(MergeRequestBase):
    name = "TerraformInit"

    def __init__(
        self, title: str, description: str, path: str, content: str, labels: list[str]
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._path = path
        self._content = content
        self.labels = labels

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=self._path,
            commit_message="add terraform state template collection",
            content=self._content,
        )


class MrData(BaseModel):
    account: str
    content: str
    path: str


class MergeRequestManager(MergeRequestManagerBase[Info]):
    """Manager for the merge requests.

    This class is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs.
    """

    def __init__(
        self, vcs: VCS, renderer: Renderer, parser: Parser, auto_merge_enabled: bool
    ):
        super().__init__(vcs, parser, LABEL)
        self._renderer = renderer
        self._auto_merge_enabled = auto_merge_enabled

    def create_merge_request(self, data: MrData) -> None:
        """Open a new MR, if not already present, for an AWS account and close any outdated before."""
        if not self._housekeeping_ran:
            self.housekeeping()

        if self._merge_request_already_exists({"account": data.account}):
            logging.info("MR already exists for %s", data.account)
            return None

        try:
            self._vcs.get_file_content_from_app_interface_ref(file_path=data.path)
            # the file exists, nothing to do
            return None
        except GitlabGetError as e:
            if e.response_code != 404:
                raise

        description = self._renderer.render_description(account=data.account)
        title = self._renderer.render_title(account=data.account)
        logging.info("Open MR for %s", data.account)
        mr_labels = [LABEL]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        self._vcs.open_app_interface_merge_request(
            mr=TerraformInitMR(
                path=data.path,
                title=title,
                description=description,
                content=data.content,
                labels=mr_labels,
            )
        )
