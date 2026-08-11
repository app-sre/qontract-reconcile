"""Tests for VCS schema path validation (defense-in-depth against path traversal)."""

import pytest
from pydantic import ValidationError

from qontract_api.external.vcs.router import VCSQueryParams
from qontract_api.external.vcs.schemas import (
    FileSyncCreate,
    FileSyncDelete,
    FileSyncUpdate,
    GetFileParams,
)

TRAVERSAL_PATHS = [
    "../etc/passwd",
    "../../etc/passwd",
    "data/../../etc/passwd",
    "data/..",
    "..",
]

VALID_PATHS = [
    "OWNERS",
    "/OWNERS",
    "data/users/alice.yml",
    "/data/users/alice.yml",
    "path/to/OWNERS",
]


@pytest.mark.parametrize("file_path", TRAVERSAL_PATHS)
def test_get_file_params_rejects_path_traversal(file_path: str) -> None:
    with pytest.raises(ValidationError):
        GetFileParams(
            secret_manager_url="https://vault.example.com",
            path="secret/vcs/token",
            field="token",
            repo_url="https://gitlab.example.com/group/project",
            file_path=file_path,
            ref="master",
        )


@pytest.mark.parametrize("file_path", VALID_PATHS)
def test_get_file_params_accepts_valid_paths(file_path: str) -> None:
    params = GetFileParams(
        secret_manager_url="https://vault.example.com",
        path="secret/vcs/token",
        field="token",
        repo_url="https://gitlab.example.com/group/project",
        file_path=file_path,
        ref="master",
    )
    assert params.file_path == file_path


@pytest.mark.parametrize("owners_file", TRAVERSAL_PATHS)
def test_vcs_query_params_rejects_path_traversal_in_owners_file(
    owners_file: str,
) -> None:
    with pytest.raises(ValidationError):
        VCSQueryParams(
            secret_manager_url="https://vault.example.com",
            path="secret/vcs/token",
            field="token",
            repo_url="https://gitlab.example.com/group/project",
            owners_file=owners_file,
            ref="master",
        )


@pytest.mark.parametrize("owners_file", VALID_PATHS)
def test_vcs_query_params_accepts_valid_owners_file(owners_file: str) -> None:
    params = VCSQueryParams(
        secret_manager_url="https://vault.example.com",
        path="secret/vcs/token",
        field="token",
        repo_url="https://gitlab.example.com/group/project",
        owners_file=owners_file,
        ref="master",
    )
    assert params.owners_file == owners_file


@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_file_sync_create_rejects_path_traversal(path: str) -> None:
    with pytest.raises(ValidationError):
        FileSyncCreate(path=path, content="content", commit_message="add file")


@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_file_sync_update_rejects_path_traversal(path: str) -> None:
    with pytest.raises(ValidationError):
        FileSyncUpdate(path=path, content="content", commit_message="update file")


@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_file_sync_delete_rejects_path_traversal(path: str) -> None:
    with pytest.raises(ValidationError):
        FileSyncDelete(path=path, commit_message="delete file")


@pytest.mark.parametrize("path", VALID_PATHS)
def test_file_sync_create_accepts_valid_paths(path: str) -> None:
    action = FileSyncCreate(path=path, content="content", commit_message="add file")
    assert action.path == path
