from unittest.mock import (
    MagicMock,
    create_autospec,
)

from github import Github
from github.ContentFile import ContentFile
from github.Repository import Repository

from reconcile.utils.github_api import GithubRepositoryApi


def github(multiple_contents: bool = False):
    github_mock = create_autospec(spec=Github)
    repo_mock = create_autospec(spec=Repository)
    get_content_mock = MagicMock()
    repo_mock.get_contents = get_content_mock
    content_file = create_autospec(spec=ContentFile)
    content_file.decoded_content = b"test"
    get_content_mock.side_effect = [content_file]
    if multiple_contents:
        get_content_mock.side_effect = [[content_file, content_file]]
    github_mock.get_repo = MagicMock()
    github_mock.get_repo.side_effect = [repo_mock]
    return github_mock


def test_create():
    gh = github()
    GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=gh,
    )
    gh.get_repo.assert_called_once_with("my/repo")


def test_get_file_default():
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo", token="some-token", github=github()
    )
    content = api.get_file(path="some/path")
    assert content == b"test"
    api._repo.get_contents.assert_called_once_with(  # type: ignore[attr-defined]
        path="some/path",
        ref="master",
    )


def test_get_file_with_ref():
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo", token="some-token", github=github()
    )
    content = api.get_file(path="some/path", ref="some-ref")
    assert content == b"test"
    api._repo.get_contents.assert_called_once_with(  # type: ignore[attr-defined]
        path="some/path",
        ref="some-ref",
    )


def test_get_file_list_returned():
    api = GithubRepositoryApi(
        repo_url="https://github.com/my/repo",
        token="some-token",
        github=github(multiple_contents=True),
    )
    content = api.get_file(path="some/path")
    assert content is None
    api._repo.get_contents.assert_called_once_with(  # type: ignore[attr-defined]
        path="some/path",
        ref="master",
    )
