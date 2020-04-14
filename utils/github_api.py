import os
from pathlib import Path
from urllib.parse import urlparse

import github

from utils import secret_reader


GH_BASE_URL = os.environ.get('GITHUB_API', 'https://api.github.com')


class GithubApi:
    def __init__(self, instance, project_url, settings):
        parsed_project_url = urlparse(project_url)
        name_with_namespace = parsed_project_url.path.strip('/')
        token = secret_reader.read(instance['token'], settings=settings)
        git_cli = github.Github(token, base_url=GH_BASE_URL)
        self.project = git_cli.get_repo(name_with_namespace)

    def get_repository_tree(self, ref):
        tree_items = []
        for item in self.project.get_git_tree(sha=ref, recursive=True).tree:
            tree_item = {'path': item.path,
                         'name': Path(item.path).name}
            tree_items.append(tree_item)
        return tree_items

    def get_file(self, path, ref):
        try:
            return self.project.get_file_contents(path, ref).decoded_content
        except github.UnknownObjectException:
            return None
