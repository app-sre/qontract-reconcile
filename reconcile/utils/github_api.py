import base64
import os
from pathlib import Path
from types import TracebackType
from urllib.parse import urlparse

from github import Commit, Github, GithubException, UnknownObjectException
from github.Repository import Repository
from sretoolbox.utils import retry

GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")

MAX_FILE_CONTENT_SIZE = 1024**2  # 1MB


class UnsupportedDirectoryError(Exception):
    pass


class GithubRepositoryApi:
    """
    Github client implementing the common interfaces used in
    the qontract-reconcile integrations.

    :param repo_url: the Github repository URL
    :param token: auth token for Github
    :type repo_url: str
    :type token: str
    """

    def __init__(
        self,
        repo_url: str,
        token: str,
        timeout: int = 30,
        github: Github | None = None,
    ):
        parsed_repo_url = urlparse(repo_url)
        repo = parsed_repo_url.path.strip("/")

        git_cli = github
        if not git_cli:
            git_cli = Github(token, base_url=GH_BASE_URL, timeout=timeout)
        self._repo = git_cli.get_repo(repo)

    def __enter__(self) -> "GithubRepositoryApi":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()

    def __str__(self) -> str:
        return self._repo.html_url

    def cleanup(self) -> None:
        """
        Align with GitLabApi
        """

    def get_repository_tree(
        self,
        *,
        ref: str = "master",
        recursive: bool = False,
    ) -> list[dict[str, str]]:
        tree_items = []
        for item in self._repo.get_git_tree(sha=ref, recursive=recursive).tree:
            tree_item = {"path": item.path, "name": Path(item.path).name}
            tree_items.append(tree_item)
        return tree_items

    @staticmethod
    def get_raw_file(
        repo: Repository,
        path: str,
        ref: str,
    ) -> bytes:
        content = repo.get_contents(path=path, ref=ref)
        if isinstance(content, list):
            raise UnsupportedDirectoryError(
                f"Path {path} of ref {ref} in repo {repo.full_name} is a directory!"
            )
        if content.size < MAX_FILE_CONTENT_SIZE:
            return content.decoded_content
        blob = repo.get_git_blob(content.sha)
        return base64.b64decode(blob.content)

    @retry()
    def get_file(
        self,
        path: str,
        ref: str = "master",
    ) -> bytes | None:
        try:
            return self.get_raw_file(
                repo=self._repo,
                path=path,
                ref=ref,
            )
        except UnsupportedDirectoryError:
            return None
        except GithubException as e:
            # handling a bug in the upstream GH library
            # https://github.com/PyGithub/PyGithub/issues/3179
            if e.status == 404:
                return None
            else:
                raise e
        except UnknownObjectException:
            return None

    @retry()
    def get_commit_sha(self, ref: str) -> str:
        return self._repo.get_commit(sha=ref).sha

    @retry()
    def compare(self, commit_from: str, commit_to: str) -> list[Commit.Commit]:
        return self._repo.compare(commit_from, commit_to).commits
