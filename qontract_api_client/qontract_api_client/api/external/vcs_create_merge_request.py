from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_merge_request_request import CreateMergeRequestRequest
from ...models.create_merge_request_response import CreateMergeRequestResponse
from ...types import Response


def _get_kwargs(
    *,
    body: CreateMergeRequestRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/external/vcs/merge-requests",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CreateMergeRequestResponse:
    if response.status_code == 201:
        response_201 = CreateMergeRequestResponse.from_dict(response.json())

        return response_201

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[CreateMergeRequestResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: CreateMergeRequestRequest,
) -> Response[CreateMergeRequestResponse]:
    """Create Merge Request

     Create a merge request with file changes in a VCS repository.

    Creates a new branch, applies file operations (create/update/delete),
    and opens a merge request against the target branch.

    Callers should use ``GET /merge-requests`` to check for existing MRs
    before calling this endpoint to avoid duplicate creation.

    Args:
        request: Merge request details including repo, auth, and file operations

    Returns:
        CreateMergeRequestResponse with the URL of the created merge request

    Args:
        body (CreateMergeRequestRequest): Request to create a merge request in a VCS repository.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateMergeRequestResponse]
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
    client: AuthenticatedClient | Client,
    body: CreateMergeRequestRequest,
) -> CreateMergeRequestResponse:
    """Create Merge Request

     Create a merge request with file changes in a VCS repository.

    Creates a new branch, applies file operations (create/update/delete),
    and opens a merge request against the target branch.

    Callers should use ``GET /merge-requests`` to check for existing MRs
    before calling this endpoint to avoid duplicate creation.

    Args:
        request: Merge request details including repo, auth, and file operations

    Returns:
        CreateMergeRequestResponse with the URL of the created merge request

    Args:
        body (CreateMergeRequestRequest): Request to create a merge request in a VCS repository.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateMergeRequestResponse
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
    client: AuthenticatedClient | Client,
    body: CreateMergeRequestRequest,
) -> Response[CreateMergeRequestResponse]:
    """Create Merge Request

     Create a merge request with file changes in a VCS repository.

    Creates a new branch, applies file operations (create/update/delete),
    and opens a merge request against the target branch.

    Callers should use ``GET /merge-requests`` to check for existing MRs
    before calling this endpoint to avoid duplicate creation.

    Args:
        request: Merge request details including repo, auth, and file operations

    Returns:
        CreateMergeRequestResponse with the URL of the created merge request

    Args:
        body (CreateMergeRequestRequest): Request to create a merge request in a VCS repository.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateMergeRequestResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: CreateMergeRequestRequest,
) -> CreateMergeRequestResponse:
    """Create Merge Request

     Create a merge request with file changes in a VCS repository.

    Creates a new branch, applies file operations (create/update/delete),
    and opens a merge request against the target branch.

    Callers should use ``GET /merge-requests`` to check for existing MRs
    before calling this endpoint to avoid duplicate creation.

    Args:
        request: Merge request details including repo, auth, and file operations

    Returns:
        CreateMergeRequestResponse with the URL of the created merge request

    Args:
        body (CreateMergeRequestRequest): Request to create a merge request in a VCS repository.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateMergeRequestResponse
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
