import logging

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase

# from reconcile.utils.mr.labels import AUTO_MERGE

LOG = logging.getLogger(__name__)


class SAPMMR(MergeRequestBase):
    name = "SAPM"

    def __init__(
        self,
        file_path: str,
        content: str,
        description: str,
        title: str,
        sapm_label: str,
    ):
        super().__init__()
        self._content = content
        self._title = title
        self._description = description
        self._file_path = file_path
        # TODO: enable auto-merge again
        # self.labels = [AUTO_MERGE, sapm_label]
        self.labels = [sapm_label]

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        msg = self._title
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=f"data{self._file_path}",
            commit_message=msg,
            content=self._content,
        )
