from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.glitchtip_project_alerts_reconcile_request import (
    GlitchtipProjectAlertsReconcileRequest,
)
from ...models.glitchtip_project_alerts_task_response import (
    GlitchtipProjectAlertsTaskResponse,
)
from ...types import Response


def _get_kwargs(
    *,
    body: GlitchtipProjectAlertsReconcileRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/integrations/glitchtip-project-alerts/reconcile",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> GlitchtipProjectAlertsTaskResponse:
    if response.status_code == 202:
        response_202 = GlitchtipProjectAlertsTaskResponse.from_dict(response.json())

        return response_202

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[GlitchtipProjectAlertsTaskResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: GlitchtipProjectAlertsReconcileRequest,
) -> Response[GlitchtipProjectAlertsTaskResponse]:
    """Glitchtip Project Alerts

     Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url

    Args:
        body (GlitchtipProjectAlertsReconcileRequest): Request model for Glitchtip project alerts
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GlitchtipProjectAlertsTaskResponse]
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
    body: GlitchtipProjectAlertsReconcileRequest,
) -> GlitchtipProjectAlertsTaskResponse:
    """Glitchtip Project Alerts

     Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url

    Args:
        body (GlitchtipProjectAlertsReconcileRequest): Request model for Glitchtip project alerts
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GlitchtipProjectAlertsTaskResponse
    """

    parsed = sync_detailed(
        client=client,
        body=body,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: GlitchtipProjectAlertsReconcileRequest,
) -> Response[GlitchtipProjectAlertsTaskResponse]:
    """Glitchtip Project Alerts

     Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url

    Args:
        body (GlitchtipProjectAlertsReconcileRequest): Request model for Glitchtip project alerts
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[GlitchtipProjectAlertsTaskResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: GlitchtipProjectAlertsReconcileRequest,
) -> GlitchtipProjectAlertsTaskResponse:
    """Glitchtip Project Alerts

     Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url

    Args:
        body (GlitchtipProjectAlertsReconcileRequest): Request model for Glitchtip project alerts
            reconciliation.

            POST requests always queue a background task (async execution).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        GlitchtipProjectAlertsTaskResponse
    """

    parsed = (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
