import base64
from unittest.mock import (
    Mock,
    create_autospec,
)

import pytest
from github import Github
from github.ContentFile import ContentFile
from github.GitBlob import GitBlob
from github.Repository import Repository

from reconcile.utils.github_api import GithubRepositoryApi, UnsupportedDirectoryError


@pytest.fixture
def github() -> Mock:
    github_mock = create_autospec(spec=Github)
    repo_mock = create_autospec(spec=Repository)
    github_mock.get_repo.return_value = repo_mock
    return github_mock


def test_create(github: Mock) -> None:
    GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github,
    )
    github.get_repo.assert_called_once_with("my/repo")


def test_get_file_default(github: Mock) -> None:
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github,
    )
    repo = github.get_repo.return_value
    expected_content = b"test"
    mocked_file = create_autospec(spec=ContentFile, size=len(expected_content))
    repo.get_contents.return_value = mocked_file
    mocked_file.decoded_content = expected_content

    content = api.get_file(path="some/path")

    assert content == expected_content
    repo.get_contents.assert_called_once_with(
        path="some/path",
        ref="master",
    )


def test_get_file_with_ref(github: Mock) -> None:
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github,
    )
    repo = github.get_repo.return_value
    expected_content = b"test"
    mocked_file = create_autospec(spec=ContentFile, size=len(expected_content))
    repo.get_contents.return_value = mocked_file
    mocked_file.decoded_content = expected_content

    content = api.get_file(path="some/path", ref="some-ref")

    assert content == expected_content
    repo.get_contents.assert_called_once_with(
        path="some/path",
        ref="some-ref",
    )


def test_get_file_list_returned(github: Mock) -> None:
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github,
    )
    repo = github.get_repo.return_value
    mocked_file = create_autospec(spec=ContentFile)
    repo.get_contents.return_value = [mocked_file]

    content = api.get_file(path="some/path")

    assert content is None
    repo.get_contents.assert_called_once_with(
        path="some/path",
        ref="master",
    )


def test_get_file_with_large_file(github: Mock) -> None:
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github,
    )
    repo = github.get_repo.return_value
    sha = "3a0f86fb8db8eea7ccbb9a95f325ddbedfb25e15"
    mocked_file = create_autospec(spec=ContentFile, size=1024 * 1024, sha=sha)  # 1MB
    repo.get_contents.return_value = mocked_file
    mocked_blob = create_autospec(spec=GitBlob)
    expected_content = b"large content"
    mocked_blob.content = base64.b64encode(expected_content)
    repo.get_git_blob.return_value = mocked_blob

    content = api.get_file(path="some/path")

    assert content == expected_content
    repo.get_contents.assert_called_once_with(
        path="some/path",
        ref="master",
    )
    repo.get_git_blob.assert_called_once_with(sha)


def test_get_raw_file(github: Mock) -> None:
    repo = create_autospec(Repository)
    expected_content = b"test"
    mocked_file = create_autospec(spec=ContentFile, size=len(expected_content))
    repo.get_contents.return_value = mocked_file
    mocked_file.decoded_content = expected_content

    content = GithubRepositoryApi.get_raw_file(
        path="some/path", ref="some-ref", repo=repo
    )

    assert content == expected_content
    repo.get_contents.assert_called_once_with(
        path="some/path",
        ref="some-ref",
    )


def test_get_raw_file_with_multiple_contents(github: Mock) -> None:
    repo = create_autospec(Repository, full_name="my/repo")
    mocked_file = create_autospec(spec=ContentFile, size=10)
    repo.get_contents.return_value = [mocked_file]

    with pytest.raises(
        UnsupportedDirectoryError,
        match=r"Path some/path of ref some-ref in repo my/repo is a directory!",
    ):
        GithubRepositoryApi.get_raw_file(path="some/path", ref="some-ref", repo=repo)
