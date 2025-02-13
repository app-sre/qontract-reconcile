import logging
from typing import cast

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS

AWS_MGR = "aws-account-manager"


class AwsAccountMR(MergeRequestBase):
    name = "AwsAccount"

    def __init__(
        self,
        title: str,
        description: str,
        account_tmpl_file_path: str,
        account_tmpl_file_content: str,
        account_request_file_path: str,
        labels: list[str],
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._account_tmpl_file_path = account_tmpl_file_path.lstrip("/")
        self._account_tmpl_file_content = account_tmpl_file_content
        self._account_request_file_path = account_request_file_path.lstrip("/")
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
            file_path=self._account_tmpl_file_path,
            commit_message="add account template file",
            content=self._account_tmpl_file_content,
        )
        gitlab_cli.delete_file(
            branch_name=self.branch,
            file_path=self._account_request_file_path,
            commit_message="delete account request file",
        )


class MergeRequestManager:
    """Manager for AWS account merge requests."""

    def __init__(self, vcs: VCS, auto_merge_enabled: bool):
        self._open_mrs: list[ProjectMergeRequest] = []
        self._vcs = vcs
        self._auto_merge_enabled = auto_merge_enabled

    def _merge_request_already_exists(self, aws_account_file_path: str) -> bool:
        return any(
            aws_account_file_path == diff["new_path"]
            for mr in self._open_mrs
            for diff in cast(dict, mr.changes())["changes"]
        )

    def fetch_open_merge_requests(self) -> None:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        self._open_mrs = [mr for mr in all_open_mrs if AWS_MGR in mr.labels]

    def create_account_file(
        self,
        title: str,
        account_tmpl_file_path: str,
        account_tmpl_file_content: str,
        account_request_file_path: str,
    ) -> None:
        """Open new MR (if not already present) for an AWS account and remove the account request file."""
        if self._merge_request_already_exists(account_tmpl_file_path):
            return None

        try:
            self._vcs.get_file_content_from_app_interface_ref(
                file_path=account_tmpl_file_path
            )
            # File already exists. nothing to do.
            logging.debug(
                "The template collection file %s already exists. This may happen if the MR has been merged but template-renderer isn't running yet.",
                account_tmpl_file_path,
            )
            return
        except GitlabGetError as e:
            if e.response_code != 404:
                raise e

        logging.info("Open MR for %s", account_tmpl_file_path)
        mr_labels = [AWS_MGR]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        self._vcs.open_app_interface_merge_request(
            mr=AwsAccountMR(
                title=title,
                description=f"New AWS account template collection file {account_tmpl_file_path}",
                account_tmpl_file_path=account_tmpl_file_path,
                account_tmpl_file_content=account_tmpl_file_content,
                account_request_file_path=account_request_file_path,
                labels=mr_labels,
            )
        )
