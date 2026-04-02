from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.aws_account_manager_reconcile_request import (
    AWSAccountManagerReconcileRequest,
)
from ...models.aws_account_manager_task_response import AWSAccountManagerTaskResponse
from ...types import Response


def _get_kwargs(
    *,
    body: AWSAccountManagerReconcileRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/integrations/aws-account-manager/reconcile",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> AWSAccountManagerTaskResponse:
    if response.status_code == 202:
        response_202 = AWSAccountManagerTaskResponse.from_dict(response.json())

        return response_202

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[AWSAccountManagerTaskResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: AWSAccountManagerReconcileRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Reconcile

     Queue reconciliation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerReconcileRequest): Request to reconcile a single AWS account.

            If ``organization`` is present, the account is treated as an organization
            account (payer credentials + role assumption). Otherwise it is a standalone
            account with direct credentials.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AWSAccountManagerTaskResponse]
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
    body: AWSAccountManagerReconcileRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Reconcile

     Queue reconciliation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerReconcileRequest): Request to reconcile a single AWS account.

            If ``organization`` is present, the account is treated as an organization
            account (payer credentials + role assumption). Otherwise it is a standalone
            account with direct credentials.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AWSAccountManagerTaskResponse
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
    body: AWSAccountManagerReconcileRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Reconcile

     Queue reconciliation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerReconcileRequest): Request to reconcile a single AWS account.

            If ``organization`` is present, the account is treated as an organization
            account (payer credentials + role assumption). Otherwise it is a standalone
            account with direct credentials.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[AWSAccountManagerTaskResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: AWSAccountManagerReconcileRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Reconcile

     Queue reconciliation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerReconcileRequest): Request to reconcile a single AWS account.

            If ``organization`` is present, the account is treated as an organization
            account (payer credentials + role assumption). Otherwise it is a standalone
            account with direct credentials.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        AWSAccountManagerTaskResponse
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
