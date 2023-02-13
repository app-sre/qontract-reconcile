import logging

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

LOG = logging.getLogger(__name__)


# TODO: remove
class DoNotPromote(Exception):
    pass


class SAPMMR(MergeRequestBase):
    name = "SAPM"

    def __init__(self, content: str, description: str, title: str, sapm_label: str):
        super().__init__()
        self._content = content
        self._title = title
        self._description = description
        self.labels = [AUTO_MERGE, sapm_label]

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        # TODO: remove
        raise DoNotPromote("I dont want to open a MR")
        # msg = f"auto-promote {self._subscriber.desired_ref} in {self._subscriber.target_file_path}"
        # gitlab_cli.update_file(
        #     branch_name=self.branch,
        #     file_path=f"data{self._subscriber.target_file_path}",
        #     commit_message=msg,
        #     content=self._content,
        # )
