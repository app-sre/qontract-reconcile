from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.glitchtip_project_alerts_task_result import (
    GlitchtipProjectAlertsTaskResult,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    task_id: str,
    *,
    timeout: int | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_timeout: int | None | Unset
    if isinstance(timeout, Unset):
        json_timeout = UNSET
    else:
        json_timeout = timeout
    params["timeout"] = json_timeout

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/integrations/glitchtip-project-alerts/reconcile/{task_id}".format(
            task_id=quote(str(task_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> GlitchtipProjectAlertsTaskResult:
    if response.status_code == 200:
        response_200 = GlitchtipProjectAlertsTaskResult.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[GlitchtipProjectAlertsTaskResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> Response[GlitchtipProjectAlertsTaskResult]:
    """Glitchtip Project Alerts Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion. Omit for
            immediate status check.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GlitchtipProjectAlertsTaskResult]
    """

    kwargs = _get_kwargs(
        task_id=task_id,
        timeout=timeout,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> GlitchtipProjectAlertsTaskResult:
    """Glitchtip Project Alerts Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion. Omit for
            immediate status check.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GlitchtipProjectAlertsTaskResult
    """

    parsed = sync_detailed(
        task_id=task_id,
        client=client,
        timeout=timeout,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> Response[GlitchtipProjectAlertsTaskResult]:
    """Glitchtip Project Alerts Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion. Omit for
            immediate status check.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GlitchtipProjectAlertsTaskResult]
    """

    kwargs = _get_kwargs(
        task_id=task_id,
        timeout=timeout,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> GlitchtipProjectAlertsTaskResult:
    """Glitchtip Project Alerts Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion. Omit for
            immediate status check.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GlitchtipProjectAlertsTaskResult
    """

    parsed = (
        await asyncio_detailed(
            task_id=task_id,
            client=client,
            timeout=timeout,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
