from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.aws_account_manager_create_iam_user_request import (
    AWSAccountManagerCreateIAMUserRequest,
)
from ...models.aws_account_manager_task_response import AWSAccountManagerTaskResponse
from ...types import Response


def _get_kwargs(
    *,
    body: AWSAccountManagerCreateIAMUserRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/integrations/aws-account-manager/create-iam-user",
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
    body: AWSAccountManagerCreateIAMUserRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Create Iam User

     Queue creation of an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    Use GET /create-iam-user/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerCreateIAMUserRequest): Request to create an IAM user in an AWS
            account.

            Assumes into the account via the payer's manager role and creates
            an IAM user with the specified policy. Credentials are saved to Vault.

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
    body: AWSAccountManagerCreateIAMUserRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Create Iam User

     Queue creation of an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    Use GET /create-iam-user/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerCreateIAMUserRequest): Request to create an IAM user in an AWS
            account.

            Assumes into the account via the payer's manager role and creates
            an IAM user with the specified policy. Credentials are saved to Vault.

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
    body: AWSAccountManagerCreateIAMUserRequest,
) -> Response[AWSAccountManagerTaskResponse]:
    """Aws Account Manager Create Iam User

     Queue creation of an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    Use GET /create-iam-user/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerCreateIAMUserRequest): Request to create an IAM user in an AWS
            account.

            Assumes into the account via the payer's manager role and creates
            an IAM user with the specified policy. Credentials are saved to Vault.

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
    body: AWSAccountManagerCreateIAMUserRequest,
) -> AWSAccountManagerTaskResponse:
    """Aws Account Manager Create Iam User

     Queue creation of an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    Use GET /create-iam-user/{task_id} to retrieve the result.

    Args:
        body (AWSAccountManagerCreateIAMUserRequest): Request to create an IAM user in an AWS
            account.

            Assumes into the account via the payer's manager role and creates
            an IAM user with the specified policy. Credentials are saved to Vault.

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
