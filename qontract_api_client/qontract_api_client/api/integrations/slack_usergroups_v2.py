from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.slack_usergroups_reconcile_request_v2 import (
    SlackUsergroupsReconcileRequestV2,
)
from ...models.slack_usergroups_task_response import SlackUsergroupsTaskResponse
from ...types import Response


def _get_kwargs(
    *,
    body: SlackUsergroupsReconcileRequestV2,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/integrations/slack-usergroups-v2/reconcile",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> SlackUsergroupsTaskResponse | None:
    if response.status_code == 202:
        response_202 = SlackUsergroupsTaskResponse.from_dict(response.json())

        return response_202

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[SlackUsergroupsTaskResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: SlackUsergroupsReconcileRequestV2,
) -> Response[SlackUsergroupsTaskResponse]:
    """Slack Usergroups

     Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url

    Args:
        body (SlackUsergroupsReconcileRequestV2): Request model for Slack usergroups
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[SlackUsergroupsTaskResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: SlackUsergroupsReconcileRequestV2,
) -> SlackUsergroupsTaskResponse | None:
    """Slack Usergroups

     Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url

    Args:
        body (SlackUsergroupsReconcileRequestV2): Request model for Slack usergroups
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        SlackUsergroupsTaskResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: SlackUsergroupsReconcileRequestV2,
) -> Response[SlackUsergroupsTaskResponse]:
    """Slack Usergroups

     Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url

    Args:
        body (SlackUsergroupsReconcileRequestV2): Request model for Slack usergroups
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[SlackUsergroupsTaskResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: SlackUsergroupsReconcileRequestV2,
) -> SlackUsergroupsTaskResponse | None:
    """Slack Usergroups

     Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url

    Args:
        body (SlackUsergroupsReconcileRequestV2): Request model for Slack usergroups
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        SlackUsergroupsTaskResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
