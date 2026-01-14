import logging

from gitlab.exceptions import GitlabGetError
from pydantic import BaseModel

from reconcile.terraform_vpc_resources.merge_request import (
    LABEL,
    Action,
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


class VPCRequestMR(MergeRequestBase):
    name = "VPCRequest"

    def __init__(
        self,
        title: str,
        description: str,
        vpc_tmpl_file_path: str,
        vpc_tmpl_file_content: str,
        labels: list[str],
        action: Action,
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._vpc_tmpl_file_path = vpc_tmpl_file_path
        self._vpc_tmpl_file_content = vpc_tmpl_file_content
        self.labels = labels
        self._action = action

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        # Create or update file based on whether it already exists
        if self._action == Action.UPDATE:
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=self._vpc_tmpl_file_path,
                commit_message="update vpc datafile",
                content=self._vpc_tmpl_file_content,
            )
        else:
            gitlab_cli.create_file(
                branch_name=self.branch,
                file_path=self._vpc_tmpl_file_path,
                commit_message="add vpc datafile",
                content=self._vpc_tmpl_file_content,
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

    def _create_action(self, data: MrData) -> Action | None:
        if self._merge_request_already_exists({"account": data.account}):
            logging.info("MR already exists for %s", data.account)
            return None
        try:
            existing_content = self._vcs.get_file_content_from_app_interface_ref(
                file_path=data.path
            )
        except GitlabGetError as e:
            if e.response_code == 404:
                return Action.CREATE
            raise

        if existing_content.strip() != data.content.strip():
            return Action.UPDATE

        logging.debug("VPC data file exists and is up-to-date for %s", data.account)
        return None

    def create_merge_request(self, data: MrData) -> None:
        """Open a new MR for VPC datafile updates, or update existing if changed."""
        if not self._housekeeping_ran:
            self.housekeeping()
        action = self._create_action(data)
        if action is None:
            return

        description = self._renderer.render_description(account=data.account)
        title = self._renderer.render_title(account=data.account, action=action)

        logging.info("Open MR for %s (%s)", data.account, action)
        mr_labels = [LABEL]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        self._vcs.open_app_interface_merge_request(
            mr=VPCRequestMR(
                vpc_tmpl_file_path=data.path,
                title=title,
                description=description,
                vpc_tmpl_file_content=data.content,
                labels=mr_labels,
                action=action,
            )
        )
