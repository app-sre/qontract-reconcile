from ruamel.yaml.compat import StringIO

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.ruamel import create_ruamel_instance


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


class PromoteQontractReconcileCommercial(MergeRequestBase):
    name = "promote_qontract_reconcile"

    def __init__(self, version: str, commit_sha: str):
        self.version = version
        self.commit_sha = commit_sha

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        return f"[{self.name}] promote qontract-reconcile to version {self.version}"

    @property
    def description(self) -> str:
        return f"promote qontract-reconcile to version {self.version}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        yml = create_ruamel_instance()

        # .env
        path = ".env"
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
        content = raw_file.decode("utf-8")
        lines = content.splitlines()
        for index, text in enumerate(lines):
            if text.startswith("export RECONCILE_IMAGE_TAG="):
                lines[index] = f"export RECONCILE_IMAGE_TAG={self.version}"
        new_content = "\n".join(lines) + "\n"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )

        # resources/jenkins/global/defaults.yaml
        path = "resources/jenkins/global/defaults.yaml"
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
        content = raw_file.decode("utf-8")
        lines = content.splitlines()
        for index, text in enumerate(lines):
            if text.startswith("    qontract_reconcile_image_tag: "):
                lines[index] = f"    qontract_reconcile_image_tag: '{self.version}'"
        new_content = "\n".join(lines) + "\n"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )

        # data/services/app-interface/cicd/ci-ext/saas-qontract-dashboards.yaml
        path = "data/services/app-interface/cicd/ci-ext/saas-qontract-dashboards.yaml"
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
        content = yml.load(raw_file)
        for rt in content["resourceTemplates"]:
            if rt["url"] == "https://github.com/app-sre/qontract-reconcile":
                for t in rt["targets"]:
                    if t["name"] == "app-sre-observability-production":
                        t["ref"] = self.commit_sha
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )

        # data/services/app-interface/cicd/ci-int/saas-qontract-manager-int.yaml
        path = "data/services/app-interface/cicd/ci-int/saas-qontract-manager-int.yaml"
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
        content = yml.load(raw_file)
        for rt in content["resourceTemplates"]:
            if rt["url"] == "https://github.com/app-sre/qontract-reconcile":
                for t in rt["targets"]:
                    if t["name"] == "app-interface-production":
                        t["ref"] = self.commit_sha
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )

        # data/pipelines/tekton-provider-global-defaults.yaml
        path = "data/pipelines/tekton-provider-global-defaults.yaml"
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
        content = yml.load(raw_file)
        for tt in content["taskTemplates"]:
            if tt["name"] == "openshift-saas-deploy":
                tt["variables"]["qontract_reconcile_image_tag"] = self.version
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )
