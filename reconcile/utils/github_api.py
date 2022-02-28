import os
from pathlib import Path
from urllib.parse import urlparse
from sretoolbox.utils import retry

import github

from reconcile.utils.secret_reader import SecretReader


GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")


class GithubApi:
    """
    Github client implementing the common interfaces used in
    the qontract-reconcile integrations.

    :param instance: the Github instance and provided
                     by the app-interface
    :param repo_url: the Github repository URL
    :param settings: the app-interface settings
    :type instance: dict
    :type repo_url: str
    :type settings: dict
    """

    def __init__(self, instance, repo_url, settings, timeout=30):
        parsed_repo_url = urlparse(repo_url)
        repo = parsed_repo_url.path.strip("/")
        secret_reader = SecretReader(settings=settings)
        token = secret_reader.read(instance["token"])
        git_cli = github.Github(token, base_url=GH_BASE_URL, timeout=timeout)
        self.repo = git_cli.get_repo(repo)

    def get_repository_tree(self, ref="master"):
        tree_items = []
        for item in self.repo.get_git_tree(sha=ref, recursive=True).tree:
            tree_item = {"path": item.path, "name": Path(item.path).name}
            tree_items.append(tree_item)
        return tree_items

    @retry()
    def get_file(self, path, ref="master"):
        try:
            return self.repo.get_contents(path, ref).decoded_content
        except github.UnknownObjectException:
            return None
