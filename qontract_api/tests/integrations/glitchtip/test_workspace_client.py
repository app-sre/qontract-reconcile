"""Unit tests for GlitchtipWorkspaceClient cache invalidation."""

from unittest.mock import MagicMock, call

import pytest
from qontract_utils.glitchtip_api import GlitchtipApi
from qontract_utils.glitchtip_api.models import Team

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.glitchtip.glitchtip_workspace_client import GlitchtipWorkspaceClient


@pytest.fixture
def mock_api() -> MagicMock:
    return MagicMock(spec=GlitchtipApi)


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def client(mock_api: MagicMock, mock_cache: MagicMock) -> GlitchtipWorkspaceClient:
    return GlitchtipWorkspaceClient(
        glitchtip_api=mock_api,
        instance_name="test-instance",
        cache=mock_cache,
        settings=Settings(),
    )


def test_delete_user_clears_team_user_caches(
    client: GlitchtipWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """delete_user must clear all team user caches for the org.

    GlitchTip removes the user from all teams when they are deleted from the org.
    Without this, the team user cache retains a stale entry and causes repeated
    remove_user_from_team 404 errors on every subsequent reconcile run.
    """
    mock_api.teams.return_value = [
        Team(pk=1, slug="team-alpha"),
        Team(pk=2, slug="team-beta"),
    ]

    client.delete_user("my-org", pk=42)

    deleted_keys = {c.args[0] for c in mock_cache.delete.call_args_list}
    assert "glitchtip:test-instance:my-org:users" in deleted_keys
    assert "glitchtip:test-instance:my-org:team-alpha:team_users" in deleted_keys
    assert "glitchtip:test-instance:my-org:team-beta:team_users" in deleted_keys
