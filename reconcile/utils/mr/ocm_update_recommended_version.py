from pydantic import BaseModel
from ruamel import yaml

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


class WorkloadRecommendedVersion(BaseModel):
    workload: str
    recommendedVersion: str


class UpdateInfo(BaseModel):
    path: str
    name: str
    recommendedVersions: list[WorkloadRecommendedVersion]


class CreateOCMUpdateRecommendedVersion(MergeRequestBase):

    name = "create_ocm_update_recommended_version_mr"

    def __init__(self, update: UpdateInfo):
        self.update = update

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] {self.update.name} ocm update recommended version"

    @property
    def description(self) -> str:
        return f"ocm update recommended version for {self.update.name}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        raw_file = gitlab_cli.project.files.get(
            file_path=self.update.path, ref=self.main_branch
        )
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        content["recommendedVersions"] = [
            k.dict() for k in self.update.recommendedVersions
        ]

        yaml.explicit_start = True  # type: ignore[attr-defined]
        new_content = yaml.dump(
            content, Dumper=yaml.RoundTripDumper, explicit_start=True
        )

        msg = f"update {self.update.name} recommended version"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.update.path,
            commit_message=msg,
            content=new_content,
        )
