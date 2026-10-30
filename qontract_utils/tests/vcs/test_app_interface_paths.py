"""Tests for app-interface GraphQL path normalization."""

import pytest
from qontract_utils.vcs.app_interface_paths import normalize_app_interface_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/access/users/alice.yml", "data/access/users/alice.yml"),
        ("access/users/alice.yml", "data/access/users/alice.yml"),
        ("data/access/users/alice.yml", "data/access/users/alice.yml"),
        ("data", "data"),
        ("  /access/users/alice.yml  ", "data/access/users/alice.yml"),
    ],
)
def test_normalize_app_interface_path(path: str, expected: str) -> None:
    """GraphQL schema-relative paths are prefixed with 'data/'.

    Already-prefixed or bare 'data' paths pass through unchanged.
    """
    assert normalize_app_interface_path(path) == expected
