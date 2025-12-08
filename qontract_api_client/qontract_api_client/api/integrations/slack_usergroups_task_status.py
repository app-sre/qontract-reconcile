from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.slack_usergroups_task_result import SlackUsergroupsTaskResult
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
        "url": f"/api/v1/integrations/slack-usergroups-v2/reconcile/{task_id}",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> SlackUsergroupsTaskResult | None:
    if response.status_code == 200:
        response_200 = SlackUsergroupsTaskResult.from_dict(response.json())

        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[SlackUsergroupsTaskResult]:
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
) -> Response[SlackUsergroupsTaskResult]:
    """Slack Usergroups Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

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
        Response[SlackUsergroupsTaskResult]
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
) -> SlackUsergroupsTaskResult | None:
    """Slack Usergroups Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

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
        SlackUsergroupsTaskResult
    """

    return sync_detailed(
        task_id=task_id,
        client=client,
        timeout=timeout,
    ).parsed


async def asyncio_detailed(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> Response[SlackUsergroupsTaskResult]:
    """Slack Usergroups Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

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
        Response[SlackUsergroupsTaskResult]
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
) -> SlackUsergroupsTaskResult | None:
    """Slack Usergroups Task Status

     Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

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
        SlackUsergroupsTaskResult
    """

    return (
        await asyncio_detailed(
            task_id=task_id,
            client=client,
            timeout=timeout,
        )
    ).parsed
