"""Tests for qontract_api.main lifespan resource management."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from qontract_api.main import lifespan


@pytest.mark.asyncio
@patch("qontract_api.event_manager._factory.get_event_manager")
@patch("qontract_api.secret_manager._factory.get_secret_manager")
@patch("qontract_api.cache.factory.get_cache")
async def test_lifespan_cleans_up_cache_when_later_startup_step_fails(
    mock_get_cache: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_event_manager: MagicMock,
) -> None:
    """A later startup failure must not leak resources created earlier."""
    mock_cache = MagicMock()
    mock_get_cache.return_value = mock_cache
    mock_get_secret_manager.side_effect = RuntimeError("boom")

    app = FastAPI()

    with pytest.raises(RuntimeError, match="boom"):
        async with lifespan(app):
            pass

    mock_cache.close.assert_called_once()
    mock_get_event_manager.assert_not_called()
