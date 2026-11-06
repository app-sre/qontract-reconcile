from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from github import Github
from github.ContentFile import ContentFile

from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder

if TYPE_CHECKING:
    from collections.abc import Callable
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

    from reconcile.utils.secret_reader import SecretReaderBase


@pytest.fixture
def saasherder(
    gql_class_factory: Callable[..., SaasFile],
    secret_reader: SecretReaderBase,
    mocker: MockerFixture,
) -> SaasHerder:
    mocker.patch.object(SaasHerder, "_get_commit_sha", return_value="commit-sha")
    return SaasHerder(
        [
            gql_class_factory(
                SaasFile, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
            )
        ],
        thread_pool_size=1,
        integration="",
        integration_version="",
        secret_reader=secret_reader,
        hash_length=7,
        repo_url="https://github.com/app-sre/app-interface",
        gitlab=mocker.create_autospec(GitLabApi, instance=True),
    )


@pytest.fixture
def github(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(Github, instance=True)


def mock_directory_contents(
    mocker: MockerFixture,
    saasherder: SaasHerder,
    github: MagicMock,
    contents: dict[str, bytes],
) -> tuple[MagicMock, MagicMock]:
    entries = []
    for name in contents:
        entry = mocker.Mock(spec=ContentFile)
        entry.name = name
        entry.type = "file"
        entries.append(entry)
    github.get_repo.return_value.get_contents.return_value = entries
    raw_file = mocker.patch(
        "reconcile.utils.saasherder.saasherder.GithubRepositoryApi.get_raw_file",
        side_effect=lambda repo, path, ref: contents[path.removeprefix("manifests/")],
    )
    assert saasherder.gitlab is not None
    gitlab_directory = mocker.patch.object(
        saasherder.gitlab,
        "get_directory_contents",
        return_value={
            f"manifests/{name}": content for name, content in contents.items()
        },
    )
    return raw_file, gitlab_directory


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_directory_loads_only_yaml_and_json(
    provider: str,
    saasherder: SaasHerder,
    github: MagicMock,
    mocker: MockerFixture,
) -> None:
    contents = {
        "first.yaml": b"kind: ConfigMap\n---\nkind: Service\n",
        "second.yml": b"kind: Deployment\n",
        "third.json": b'{"kind": "Secret", "data": null}',
        # This README reproduces the bootstrap failure when parsed as YAML.
        "README.md": (
            b"This directory contains raw manifests.\n"
            b"SaaS deploys them with `provider: directory`; later adopted.\n"
        ),
        "notes.txt": b"invalid: [",
        "extensionless": b"invalid: [",
        "backup.yaml.bak": b"invalid: [",
    }
    raw_file, gitlab_directory = mock_directory_contents(
        mocker, saasherder, github, contents
    )

    resources, commit_sha = saasherder._get_directory_contents(
        f"https://{provider}.com/app-sre/test", "manifests", "main", github
    )

    assert resources == [
        {"kind": "ConfigMap"},
        {"kind": "Service"},
        {"kind": "Deployment"},
        {"kind": "Secret", "data": None},
    ]
    assert commit_sha == "commit-sha"
    if provider == "github":
        assert [call.kwargs["path"] for call in raw_file.call_args_list] == [
            "manifests/first.yaml",
            "manifests/second.yml",
            "manifests/third.json",
        ]
    else:
        raw_file.assert_not_called()
        gitlab_directory.assert_called_once_with(
            mocker.ANY,
            ref="commit-sha",
            path="manifests",
            recursive=False,
        )


@pytest.mark.usefixtures("patch_sleep")
@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("extension", ["yaml", "yml", "json"])
def test_directory_rejects_invalid_manifest(
    provider: str,
    extension: str,
    saasherder: SaasHerder,
    github: MagicMock,
    mocker: MockerFixture,
) -> None:
    mock_directory_contents(
        mocker, saasherder, github, {f"broken.{extension}": b"invalid: ["}
    )

    with pytest.raises(yaml.YAMLError):
        saasherder._get_directory_contents(
            f"https://{provider}.com/app-sre/test", "manifests", "main", github
        )


@pytest.mark.usefixtures("patch_sleep")
@pytest.mark.parametrize("name", ["nested", "nested.yaml", "nested.md"])
def test_github_directory_rejects_subdirectories(
    name: str,
    saasherder: SaasHerder,
    github: MagicMock,
    mocker: MockerFixture,
) -> None:
    raw_file, _ = mock_directory_contents(mocker, saasherder, github, {})
    directory = mocker.Mock(spec=ContentFile)
    directory.name = name
    directory.type = "dir"
    github.get_repo.return_value.get_contents.return_value = [directory]

    with pytest.raises(ValueError, match=f"Nested directory 'manifests/{name}'"):
        saasherder._get_directory_contents(
            "https://github.com/app-sre/test", "manifests", "main", github
        )

    raw_file.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        yaml.YAMLError("invalid YAML"),
        RuntimeError("GitHub unavailable"),
        ValueError("Nested directory 'manifests/nested' is not supported"),
    ],
)
def test_directory_logs_actual_error(
    error: Exception,
    saasherder: SaasHerder,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch.object(saasherder, "_get_directory_contents", side_effect=error)
    spec = mocker.Mock(provider="directory", error_prefix="[test]")

    with pytest.raises(type(error)):
        saasherder._process_template(spec)

    assert caplog.messages == [f"[test] error loading directory: {error}"]
