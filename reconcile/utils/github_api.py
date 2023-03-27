import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from github import (
    Github,
    UnknownObjectException,
)
from sretoolbox.utils import retry

GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")


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
        github: Optional[Github] = None,
    ):
        parsed_repo_url = urlparse(repo_url)
        repo = parsed_repo_url.path.strip("/")

        git_cli = github
        if not git_cli:
            git_cli = Github(token, base_url=GH_BASE_URL, timeout=timeout)
        self._repo = git_cli.get_repo(repo)

    def get_repository_tree(self, ref: str = "master") -> list[dict[str, str]]:
        tree_items = []
        for item in self._repo.get_git_tree(sha=ref, recursive=True).tree:
            tree_item = {"path": item.path, "name": Path(item.path).name}
            tree_items.append(tree_item)
        return tree_items

    @retry()
    def get_file(self, path: str, ref: str = "master") -> Optional[bytes]:
        try:
            content = self._repo.get_contents(path=path, ref=ref)
            if isinstance(content, list):
                # TODO: we should probably raise an exception here
                # or handle this properly
                # -> for now staying backwards compatible
                return None
            return content.decoded_content
        except UnknownObjectException:
            return None

    @retry()
    def get_commit_sha(self, ref: str) -> str:
        return self._repo.get_commit(sha=ref).sha
