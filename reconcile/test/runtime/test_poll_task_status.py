"""Tests for QontractReconcileApiIntegration.poll_task_status."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)


class _SampleResult(BaseModel):
    ok: bool = True


class _Integration(QontractReconcileApiIntegration[PydanticRunParams]):
    @property
    def name(self) -> str:
        return "test-integration"

    async def async_run(self, dry_run: bool) -> None:
        return None


@pytest.mark.asyncio
async def test_poll_task_status_omits_timeout_query_when_none() -> None:
    integration = _Integration(PydanticRunParams())
    arequest = AsyncMock(return_value=_SampleResult())

    with patch(
        "reconcile.utils.runtime.integration.qontract_api_client.arequest",
        new=arequest,
    ):
        await integration.poll_task_status(
            status_url="https://api.example/api/v1/foo/status/1",
            result_type=_SampleResult,
            timeout=None,
        )

    assert "query" not in arequest.await_args.kwargs


@pytest.mark.asyncio
async def test_poll_task_status_sends_timeout_query_when_set() -> None:
    integration = _Integration(PydanticRunParams())
    arequest = AsyncMock(return_value=_SampleResult())

    with patch(
        "reconcile.utils.runtime.integration.qontract_api_client.arequest",
        new=arequest,
    ):
        await integration.poll_task_status(
            status_url="https://api.example/api/v1/foo/status/1",
            result_type=_SampleResult,
            timeout=120,
        )

    assert arequest.await_args.kwargs["query"] == {"timeout": 120}
