import logging
from collections.abc import Mapping

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

LOG = logging.getLogger(__name__)


class SAPMMR(MergeRequestBase):
    """
    Very thin wrapper around MergeRequestBase.
    This class is not tested, thus logic in here
    is kept to a minimum. Any rendering should
    happen in renderer.py
    """

    name = "SAPM"

    def __init__(
        self,
        content_by_path: Mapping[str, str],
        description: str,
        title: str,
        sapm_label: str,
    ):
        super().__init__()
        self._content_by_path = content_by_path
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
        for path, content in self._content_by_path.items():
            msg = "auto-promote subscriber"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=f"data{path}",
                commit_message=msg,
                content=content,
            )
