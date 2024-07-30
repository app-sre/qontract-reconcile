from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase


class PromoteQontractSchemas(MergeRequestBase):
    name = "promote_qontract_schemas"

    def __init__(self, version: str):
        self.path = ".env"
        self.version = version

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        return f"[{self.name}] promote qontract-schemas to version {self.version}"

    @property
    def description(self) -> str:
        return f"promote qontract-schemas to version {self.version}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        raw_file = gitlab_cli.project.files.get(
            file_path=self.path, ref=gitlab_cli.main_branch
        )
        content = raw_file.decode().decode("utf-8")
        lines = content.splitlines()
        for index, text in enumerate(lines):
            if text.startswith("export SCHEMAS_IMAGE_TAG="):
                lines[index] = f"export SCHEMAS_IMAGE_TAG={self.version}"

        new_content = "\n".join(lines) + "\n"

        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.path,
            commit_message=self.description,
            content=new_content,
        )
