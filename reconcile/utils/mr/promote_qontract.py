from jsonpath_ng.ext import parser
from ruamel.yaml.compat import StringIO

from reconcile import typed_queries
from reconcile.gql_definitions.fragments.user import User
from reconcile.typed_queries.users import get_users
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

    def __init__(self, version: str, commit_sha: str, author_email: str | None = None):
        self.version = version
        self.commit_sha = commit_sha
        self.author_email = author_email

        super().__init__()

        self.labels = []

    def author(self, all_users: list[User] | None = None) -> str | None:
        if not self.author_email:
            return None
        if not all_users:
            return None

        username = self.author_email.split("@")[0]
        users = None
        if self.author_email.endswith(typed_queries.smtp.settings().mail_address):
            users = [u for u in all_users if username == u.org_username]
        elif self.author_email.endswith("users.noreply.github.com"):
            users = [u for u in all_users if username == u.github_username]

        if users:
            return users[0].org_username

        return None

    @property
    def title(self) -> str:
        author = self.author(all_users=get_users())
        return f"[{self.name}] promote qontract-reconcile to version {self.version}" + (
            f" by @{author}"
            if author
            else f" by {self.author_email}"
            if self.author_email
            else ""
        )

    @property
    def description(self) -> str:
        return f"promote qontract-reconcile to version {self.version}"

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
        raw_file = gitlab_cli.project.files.get(
            file_path=path, ref=gitlab_cli.main_branch
        ).decode()
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

        # data/pipelines/tekton-provider-global-defaults.yaml
        self._process_by(
            "json_path",
            gitlab_cli=gitlab_cli,
            path="data/pipelines/tekton-provider-global-defaults.yaml",
            search_text="$.taskTemplates[?(@.name == 'openshift-saas-deploy')].variables.qontract_reconcile_image_tag",
            replace_text=self.version,
        )
