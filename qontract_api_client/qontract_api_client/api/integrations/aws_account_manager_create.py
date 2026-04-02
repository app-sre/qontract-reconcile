from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.aws_account_manager_create_account_request import (
    AWSAccountManagerCreateAccountRequest,
)
from ...models.aws_account_manager_task_response import AWSAccountManagerTaskResponse
from ...types import Response


def _get_kwargs(
    *,
    body: AWSAccountManagerCreateAccountRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/integrations/aws-account-manager/create-account",
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

    if response.status_code == 409:
        response_409 = AWSAccountManagerTaskResponse.from_dict(response.json())

        return response_409

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
    body: AWSAccountManagerCreateAccountRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Create

     Queue creation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    The task retries itself until the full workflow completes.
    Use GET /create-account/{task_id} to retrieve the result.

    Returns 409 with the original task response if a creation workflow
    for the same request is already in progress.

    Args:
        body (AWSAccountManagerCreateAccountRequest): Request to create a plain AWS account.

            Handles only AWS-level operations: create org account, describe,
            tag, set alias. One payer account + one account request per call.

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
    body: AWSAccountManagerCreateAccountRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Create

     Queue creation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    The task retries itself until the full workflow completes.
    Use GET /create-account/{task_id} to retrieve the result.

    Returns 409 with the original task response if a creation workflow
    for the same request is already in progress.

    Args:
        body (AWSAccountManagerCreateAccountRequest): Request to create a plain AWS account.

            Handles only AWS-level operations: create org account, describe,
            tag, set alias. One payer account + one account request per call.

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
    body: AWSAccountManagerCreateAccountRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Create

     Queue creation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    The task retries itself until the full workflow completes.
    Use GET /create-account/{task_id} to retrieve the result.

    Returns 409 with the original task response if a creation workflow
    for the same request is already in progress.

    Args:
        body (AWSAccountManagerCreateAccountRequest): Request to create a plain AWS account.

            Handles only AWS-level operations: create org account, describe,
            tag, set alias. One payer account + one account request per call.

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
    body: AWSAccountManagerCreateAccountRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Create

     Queue creation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    The task retries itself until the full workflow completes.
    Use GET /create-account/{task_id} to retrieve the result.

    Returns 409 with the original task response if a creation workflow
    for the same request is already in progress.

    Args:
        body (AWSAccountManagerCreateAccountRequest): Request to create a plain AWS account.

            Handles only AWS-level operations: create org account, describe,
            tag, set alias. One payer account + one account request per call.

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
