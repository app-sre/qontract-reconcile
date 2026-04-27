from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.create_merge_request_response import CreateMergeRequestResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    title: str,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["secret_manager_url"] = secret_manager_url

    params["path"] = path

    json_field: None | str | Unset
    if isinstance(field, Unset):
        json_field = UNSET
    else:
        json_field = field
    params["field"] = json_field

    json_version: int | None | Unset
    if isinstance(version, Unset):
        json_version = UNSET
    else:
        json_version = version
    params["version"] = json_version

    params["repo_url"] = repo_url

    params["title"] = title

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/external/vcs/merge-requests",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CreateMergeRequestResponse:
    if response.status_code == 200:
        response_200 = CreateMergeRequestResponse.from_dict(response.json())

        return response_200

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
    client: AuthenticatedClient,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    title: str,
) -> Response[CreateMergeRequestResponse]:
    """Find Merge Request

     Find an open merge request by title.

    Args:
        params: Query parameters with repo_url, title, and token

    Returns:
        CreateMergeRequestResponse with the MR URL

    Raises:
        HTTPException: 404 if no open MR found with the given title

    Args:
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
        title (str): MR title to search for (exact match)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateMergeRequestResponse]
    """

    kwargs = _get_kwargs(
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        title=title,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    title: str,
) -> CreateMergeRequestResponse:
    """Find Merge Request

     Find an open merge request by title.

    Args:
        params: Query parameters with repo_url, title, and token

    Returns:
        CreateMergeRequestResponse with the MR URL

    Raises:
        HTTPException: 404 if no open MR found with the given title

    Args:
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
        title (str): MR title to search for (exact match)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateMergeRequestResponse
    """

    parsed = sync_detailed(
        client=client,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        title=title,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    title: str,
) -> Response[CreateMergeRequestResponse]:
    """Find Merge Request

     Find an open merge request by title.

    Args:
        params: Query parameters with repo_url, title, and token

    Returns:
        CreateMergeRequestResponse with the MR URL

    Raises:
        HTTPException: 404 if no open MR found with the given title

    Args:
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
        title (str): MR title to search for (exact match)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CreateMergeRequestResponse]
    """

    kwargs = _get_kwargs(
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        title=title,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    title: str,
) -> CreateMergeRequestResponse:
    """Find Merge Request

     Find an open merge request by title.

    Args:
        params: Query parameters with repo_url, title, and token

    Returns:
        CreateMergeRequestResponse with the MR URL

    Raises:
        HTTPException: 404 if no open MR found with the given title

    Args:
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
        title (str): MR title to search for (exact match)

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CreateMergeRequestResponse
    """

    parsed = (
        await asyncio_detailed(
            client=client,
            secret_manager_url=secret_manager_url,
            path=path,
            field=field,
            version=version,
            repo_url=repo_url,
            title=title,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
