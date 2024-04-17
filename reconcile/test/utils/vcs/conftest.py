from collections.abc import (
    Callable,
    Mapping,
)
from datetime import datetime
from unittest.mock import create_autospec

import pytest
from github import Commit

from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.vcs import VCS


@pytest.fixture
def gitlab_api_builder() -> Callable[[Mapping], GitLabApi]:
    def builder(data: Mapping) -> GitLabApi:
        gitlab_api = create_autospec(spec=GitLabApi)
        gitlab_api.get_merge_request_pipelines.side_effect = [
            data.get("MR_PIPELINES", [])
        ]

        commits = [
            {"id": sha, "committed_date": "2021-01-01T00:00:00Z"}
            for sha in data.get("COMMITS", [])
        ]
        gitlab_api.repository_compare.side_effect = [commits]
        return gitlab_api

    return builder


@pytest.fixture
def github_api_builder() -> Callable[[Mapping], GithubRepositoryApi]:
    def builder(data: Mapping) -> GithubRepositoryApi:
        github_api = create_autospec(spec=GithubRepositoryApi)

        commits = []

        for d in data.get("COMMITS", []):
            c = create_autospec(spec=Commit.Commit)
            c.sha = d
            c.commit.committer.date = datetime.fromisoformat("2021-01-01T00:00:00Z")
            commits.append(c)

        github_api.compare.side_effect = [commits]
        return github_api

    return builder


@pytest.fixture
def vcs_builder(
    gitlab_api_builder: Callable[[Mapping], GitLabApi],
    secret_reader: SecretReaderBase,
    github_api_builder: Callable[[Mapping], GithubRepositoryApi],
) -> Callable[[Mapping], VCS]:
    def builder(data: Mapping) -> VCS:
        gitlab_api = gitlab_api_builder(data)
        github_api = github_api_builder(data)
        vcs = VCS(
            allow_deleting_mrs=False,
            allow_opening_mrs=False,
            app_interface_api=gitlab_api,
            app_interface_repo_url="",
            default_gh_token="some-token",
            github_orgs=[],
            gitlab_instance=gitlab_api,
            secret_reader=secret_reader,
            dry_run=True,
            gitlab_instances=[],
            github_api_per_repo_url={data.get("REPO", ""): github_api},
        )
        return vcs

    return builder
