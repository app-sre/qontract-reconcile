from collections.abc import (
    Callable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest

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
        return gitlab_api

    return builder


@pytest.fixture
def vcs_builder(
    gitlab_api_builder: Callable[[Mapping], GitLabApi], secret_reader: SecretReaderBase
) -> Callable[[Mapping], VCS]:
    def builder(data: Mapping) -> VCS:
        gitlab_api = gitlab_api_builder(data)
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
        )
        return vcs

    return builder
