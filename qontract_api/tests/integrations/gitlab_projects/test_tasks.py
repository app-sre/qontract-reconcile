"""Tests for gitlab-projects tasks."""

from unittest.mock import MagicMock

from qontract_api.integrations.gitlab_projects.domain import GitlabInstanceConfig
from qontract_api.integrations.gitlab_projects.tasks import generate_lock_key
from qontract_api.models import Secret


def _instance(name: str = "gitlab-cee") -> GitlabInstanceConfig:
    return GitlabInstanceConfig(
        name=name,
        url=f"https://{name}.example.com",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path=f"secret/gitlab/{name}/token",
        ),
        groups=[],
    )


def test_generate_lock_key_sorted() -> None:
    """Lock key is sorted instance names."""
    instances = [_instance("z-instance"), _instance("a-instance")]
    key = generate_lock_key(MagicMock(), instances)
    assert key == "a-instance,z-instance"


def test_generate_lock_key_single() -> None:
    key = generate_lock_key(MagicMock(), [_instance("gitlab-cee")])
    assert key == "gitlab-cee"


def test_generate_lock_key_empty() -> None:
    key = generate_lock_key(MagicMock(), [])
    assert key == ""
