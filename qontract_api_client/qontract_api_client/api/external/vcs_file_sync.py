from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.file_sync_request import FileSyncRequest
from ...models.file_sync_response import FileSyncResponse
from ...types import Response


def _get_kwargs(
    *,
    body: FileSyncRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/external/vcs/file-sync",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> FileSyncResponse:
    if response.status_code == 200:
        response_200 = FileSyncResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[FileSyncResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: FileSyncRequest,
) -> Response[FileSyncResponse]:
    """File Sync

     Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.

    Args:
        body (FileSyncRequest): Request to reconcile file state in a VCS repository.

            Deduplicates by MR title and creates a merge request with the
            given file operations. Relies on the VCS provider for validation.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FileSyncResponse]
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
    body: FileSyncRequest,
) -> FileSyncResponse:
    """File Sync

     Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.

    Args:
        body (FileSyncRequest): Request to reconcile file state in a VCS repository.

            Deduplicates by MR title and creates a merge request with the
            given file operations. Relies on the VCS provider for validation.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FileSyncResponse
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
    body: FileSyncRequest,
) -> Response[FileSyncResponse]:
    """File Sync

     Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.

    Args:
        body (FileSyncRequest): Request to reconcile file state in a VCS repository.

            Deduplicates by MR title and creates a merge request with the
            given file operations. Relies on the VCS provider for validation.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[FileSyncResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: FileSyncRequest,
) -> FileSyncResponse:
    """File Sync

     Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.

    Args:
        body (FileSyncRequest): Request to reconcile file state in a VCS repository.

            Deduplicates by MR title and creates a merge request with the
            given file operations. Relies on the VCS provider for validation.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        FileSyncResponse
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
