from ruamel import yaml

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


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
        raw_file = gitlab_cli.project.files.get(
            file_path=self.path, ref=self.main_branch
        )
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        content["recommendedVersions"] = self.recommended_versions

        yaml.explicit_start = True  # type: ignore[attr-defined]
        new_content = yaml.dump(
            content, Dumper=yaml.RoundTripDumper, explicit_start=True
        )

        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.path,
            commit_message=f"update {self.ocm_name} recommended version",
            content=new_content,
        )
