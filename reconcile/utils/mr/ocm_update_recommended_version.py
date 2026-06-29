from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.ruamel import create_ruamel_instance, dump_yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

if TYPE_CHECKING:
    from reconcile.utils.gitlab_api import GitLabApi


class CreateOCMUpdateRecommendedVersion(MergeRequestBase):
    name = "create_ocm_update_recommended_version_mr"

    def __init__(
        self, ocm_name: str, path: str, recommended_versions: list[dict[str, str]]
    ):
        self.ocm_name = ocm_name
        self.path = path
        self.recommended_versions = recommended_versions

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] {self.ocm_name} ocm update recommended version"

    @property
    def description(self) -> str:
        return f"ocm update recommended version for {self.ocm_name}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        yml = create_ruamel_instance(explicit_start=True)
        raw_file = gitlab_cli.get_raw_file(
            project=gitlab_cli.project,
            path=self.path,
            ref=gitlab_cli.main_branch,
        )
        content = yml.load(raw_file)

        content["recommendedVersions"] = self.recommended_versions

        new_content = dump_yaml(yml, content)

        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.path,
            commit_message=f"update {self.ocm_name} recommended version",
            content=new_content,
        )
