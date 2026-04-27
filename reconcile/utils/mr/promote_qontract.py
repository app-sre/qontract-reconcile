from jsonpath_ng.ext import parser
from ruamel.yaml.compat import StringIO

from reconcile.typed_queries.users import get_users
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.ruamel import create_ruamel_instance


class PromoteQontractSchemas(MergeRequestBase):
    name = "promote_qontract_schemas"

    def __init__(
        self, version: str, commit_sha: str, github_user_id: str | None = None
    ):
        self.path = ".env"
        self.version = version
        self.github_user_id = github_user_id
        # This is currently unused, however, we keep it to conform with general SQS message format
        self.commit_sha = commit_sha

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        author = self.infer_author(
            github_user_id=self.github_user_id, all_users=get_users()
        )
        return f"[{self.name}] promote qontract-schemas to version {self.version}" + (
            f" by @{author}"
            if author
            else f" by {self.github_user_id}"
            if self.github_user_id
            else ""
        )

    @property
    def description(self) -> str:
        return f"""
promote qontract-schemas to version {self.version}.

At the time of creating this MR, the konflux RPA most likely didn't finish yet, so this MR will likely fail first.
Please use `/retest` once the RPA finished (that should be the case after ~5min of creating this MR).
        """

    def process(self, gitlab_cli: GitLabApi) -> None:
        raw_file = gitlab_cli.get_raw_file(
            project=gitlab_cli.project,
            path=self.path,
            ref=gitlab_cli.main_branch,
        )
        content = raw_file.decode("utf-8")
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
    project_display_name = "qontract-reconcile"

    def __init__(
        self, version: str, commit_sha: str, github_user_id: str | None = None
    ):
        self.version = version
        self.commit_sha = commit_sha
        self.github_user_id = github_user_id

        super().__init__()

        self.labels = []

    @property
    def title(self) -> str:
        author = self.infer_author(
            github_user_id=self.github_user_id, all_users=get_users()
        )
        return (
            f"[{self.name}] promote {self.project_display_name} to version {self.version}"
            + (
                f" by @{author}"
                if author
                else f" by {self.github_user_id}"
                if self.github_user_id
                else ""
            )
        )

    @property
    def description(self) -> str:
        return f"""
promote {self.project_display_name} to version {self.version}.

At the time of creating this MR, the konflux RPA most likely didn't finish yet, so this MR will likely fail first.
Please use `/retest` once the RPA finished (that should be the case after ~5min of creating this MR).
"""

    def _process_by_line_search(
        self, raw_file: bytes, search_text: str, replace_text: str
    ) -> str:
        content = raw_file.decode("utf-8")
        lines = content.splitlines()
        for index, text in enumerate(lines):
            if text.startswith(search_text):
                lines[index] = replace_text
        new_content = "\n".join(lines) + "\n"

        return new_content

    def _process_by_json_path(
        self, raw_file: bytes, search_text: str, replace_text: str
    ) -> str:
        yml = create_ruamel_instance()
        content = yml.load(raw_file)
        for match in parser.parse(search_text).find(content):
            parent = match.context.value
            key = match.path.fields[0]
            parent[key] = replace_text
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""

        return new_content

    def _process_by(
        self,
        method: str,
        gitlab_cli: GitLabApi,
        path: str,
        search_text: str,
        replace_text: str,
    ) -> None:
        raw_file = gitlab_cli.get_raw_file(
            project=gitlab_cli.project,
            path=path,
            ref=gitlab_cli.main_branch,
        )
        match method:
            case "line_search":
                new_content = self._process_by_line_search(
                    raw_file=raw_file,
                    search_text=search_text,
                    replace_text=replace_text,
                )
            case "json_path":
                new_content = self._process_by_json_path(
                    raw_file=raw_file,
                    search_text=search_text,
                    replace_text=replace_text,
                )
            case _:
                raise NotImplementedError(method)

        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=path,
            commit_message=self.description,
            content=new_content,
        )

    def _process_file_with_json_paths(
        self,
        gitlab_cli: GitLabApi,
        path: str,
        replacements: list[tuple[str, str]],
    ) -> None:
        raw_file = gitlab_cli.get_raw_file(
            project=gitlab_cli.project,
            path=path,
            ref=gitlab_cli.main_branch,
        )
        yml = create_ruamel_instance()
        content = yml.load(raw_file)
        for search_text, replace_text in replacements:
            for match in parser.parse(search_text).find(content):
                parent = match.context.value
                key = match.path.fields[0]
                parent[key] = replace_text
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

    def process(self, gitlab_cli: GitLabApi) -> None:
        # .env
        self._process_by(
            "line_search",
            gitlab_cli=gitlab_cli,
            path=".env",
            search_text="export RECONCILE_IMAGE_TAG=",
            replace_text=f"export RECONCILE_IMAGE_TAG={self.version}",
        )

        # resources/jenkins/global/defaults.yaml
        self._process_by(
            "line_search",
            gitlab_cli=gitlab_cli,
            path="resources/jenkins/global/defaults.yaml",
            search_text="    qontract_reconcile_image_tag: ",
            replace_text=f"    qontract_reconcile_image_tag: '{self.version}'",
        )

        # data/services/app-interface/cicd/ci-ext/saas-qontract-dashboards.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/cicd/ci-ext/saas-qontract-dashboards.yaml",
            search_text="$.resourceTemplates[?(@.url == 'https://github.com/app-sre/qontract-reconcile')].targets[?(@.name == 'app-sre-observability-production')].ref",
            replace_text=self.commit_sha,
        )

        # data/services/app-interface/cicd/ci-int/saas-qontract-manager-int.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/cicd/ci-int/saas-qontract-manager-int.yaml",
            search_text="$.resourceTemplates[?(@.url == 'https://github.com/app-sre/qontract-reconcile')].targets[?(@.name == 'app-interface-production')].ref",
            replace_text=self.commit_sha,
        )

        # data/services/app-interface/cicd/ci-int/saas-qontract-api.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/cicd/ci-int/saas-qontract-api.yaml",
            search_text="$.resourceTemplates[?(@.url == 'https://github.com/app-sre/qontract-reconcile')].targets[?(@.name == 'qontract-api-production')].ref",
            replace_text=self.commit_sha,
        )

        # data/services/app-interface/terraform-repo/cicd/ci-int/saas-terraform-repo.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/terraform-repo/cicd/ci-int/saas-terraform-repo.yaml",
            search_text="$.resourceTemplates[?(@.name == 'terraform-repo')].targets[?(@.name == 'tf-repo-prod')].parameters.QR_IMAGE_TAG",
            replace_text=self.version,
        )

        # data/pipelines/tekton-provider-global-defaults.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/pipelines/tekton-provider-global-defaults.yaml",
            search_text="$.taskTemplates[?(@.name == 'openshift-saas-deploy')].variables.qontract_reconcile_image_tag",
            replace_text=self.version,
        )


class PromoteQontractServer(PromoteQontractReconcileCommercial):
    name = "promote_qontract_server"
    project_display_name = "qontract-server"

    def process(self, gitlab_cli: GitLabApi) -> None:
        # .env
        self._process_by(
            "line_search",
            gitlab_cli=gitlab_cli,
            path=".env",
            search_text="export QONTRACT_SERVER_IMAGE_TAG=",
            replace_text=f"export QONTRACT_SERVER_IMAGE_TAG={self.version}",
        )

        # data/services/app-interface/cicd/ci-ext/saas-qontract-server.yaml
        # Both the main template and dashboard share the same file — read/write once.
        self._process_file_with_json_paths(
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/cicd/ci-ext/saas-qontract-server.yaml",
            replacements=[
                (
                    "$.resourceTemplates[?(@.name == 'qontract-server')].targets[?(@.name == 'app-interface-production')].ref",
                    self.commit_sha,
                ),
                (
                    "$.resourceTemplates[?(@.name == 'qontract-server dashboard')].targets[?(@.name == 'app-sre-observability-production')].ref",
                    self.commit_sha,
                ),
            ],
        )

        # data/services/app-interface/cicd/ci-int/saas-qontract-server-int.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/app-interface/cicd/ci-int/saas-qontract-server-int.yaml",
            search_text="$.resourceTemplates[?(@.name == 'qontract-server')].targets[?(@.name == 'app-interface-production-int')].ref",
            replace_text=self.commit_sha,
        )

        # data/services/sre-capabilities/cicd/saas.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/services/sre-capabilities/cicd/saas.yaml",
            search_text="$.resourceTemplates[?(@.name == 'qontract-server')].targets[?(@.name == 'sre-capabilities-production')].ref",
            replace_text=self.commit_sha,
        )
