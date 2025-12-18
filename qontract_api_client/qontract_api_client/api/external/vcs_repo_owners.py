from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.repo_owners_response import RepoOwnersResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    url_query: str,
    path: str | Unset = "/",
    ref: str | Unset = "master",
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["url"] = url_query

    params["path"] = path

    params["ref"] = ref

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/external/vcs/repos/owners",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> RepoOwnersResponse | None:
    if response.status_code == 200:
        response_200 = RepoOwnersResponse.from_dict(response.json())

        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[RepoOwnersResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    url_query: str,
    path: str | Unset = "/",
    ref: str | Unset = "master",
) -> Response[RepoOwnersResponse]:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Path modes:
    - \"/\" - Root OWNERS file only
    - \"/path\" - Specific path with inherited owners from parent directories

    Args:
        cache: Cache backend for VCS API responses
        url: Repository URL (e.g., https://github.com/openshift/osdctl)
        path: Path mode (/, /path, or ALL)
        ref: Git reference (branch, tag, commit SHA)

    Returns:
        RepoOwnersResponse with provider type, approvers, and reviewers lists

    Raises:
        HTTPException:
            - 500 Internal Server Error: If VCS API call fails or tokens not found

    Example:
        GET /api/v1/external/vcs/repos/owners?url=https://github.com/openshift/osdctl&path=/&ref=master
        Response:
        {
            \"provider\": \"github\",
            \"approvers\": [\"github_user1\", \"github_user2\"],
            \"reviewers\": [\"github_user3\"]
        }

    Args:
        url_query (str): Repository URL (e.g., https://github.com/owner/repo)
        path (str | Unset): Path mode: '/' (root OWNERS), '/path' (specific path with inheritance)
            Default: '/'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[RepoOwnersResponse]
    """

    kwargs = _get_kwargs(
        url_query=url_query,
        path=path,
        ref=ref,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    url_query: str,
    path: str | Unset = "/",
    ref: str | Unset = "master",
) -> RepoOwnersResponse | None:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Path modes:
    - \"/\" - Root OWNERS file only
    - \"/path\" - Specific path with inherited owners from parent directories

    Args:
        cache: Cache backend for VCS API responses
        url: Repository URL (e.g., https://github.com/openshift/osdctl)
        path: Path mode (/, /path, or ALL)
        ref: Git reference (branch, tag, commit SHA)

    Returns:
        RepoOwnersResponse with provider type, approvers, and reviewers lists

    Raises:
        HTTPException:
            - 500 Internal Server Error: If VCS API call fails or tokens not found

    Example:
        GET /api/v1/external/vcs/repos/owners?url=https://github.com/openshift/osdctl&path=/&ref=master
        Response:
        {
            \"provider\": \"github\",
            \"approvers\": [\"github_user1\", \"github_user2\"],
            \"reviewers\": [\"github_user3\"]
        }

    Args:
        url_query (str): Repository URL (e.g., https://github.com/owner/repo)
        path (str | Unset): Path mode: '/' (root OWNERS), '/path' (specific path with inheritance)
            Default: '/'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        RepoOwnersResponse
    """

    return sync_detailed(
        client=client,
        url_query=url_query,
        path=path,
        ref=ref,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    url_query: str,
    path: str | Unset = "/",
    ref: str | Unset = "master",
) -> Response[RepoOwnersResponse]:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Path modes:
    - \"/\" - Root OWNERS file only
    - \"/path\" - Specific path with inherited owners from parent directories

    Args:
        cache: Cache backend for VCS API responses
        url: Repository URL (e.g., https://github.com/openshift/osdctl)
        path: Path mode (/, /path, or ALL)
        ref: Git reference (branch, tag, commit SHA)

    Returns:
        RepoOwnersResponse with provider type, approvers, and reviewers lists

    Raises:
        HTTPException:
            - 500 Internal Server Error: If VCS API call fails or tokens not found

    Example:
        GET /api/v1/external/vcs/repos/owners?url=https://github.com/openshift/osdctl&path=/&ref=master
        Response:
        {
            \"provider\": \"github\",
            \"approvers\": [\"github_user1\", \"github_user2\"],
            \"reviewers\": [\"github_user3\"]
        }

    Args:
        url_query (str): Repository URL (e.g., https://github.com/owner/repo)
        path (str | Unset): Path mode: '/' (root OWNERS), '/path' (specific path with inheritance)
            Default: '/'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[RepoOwnersResponse]
    """

    kwargs = _get_kwargs(
        url_query=url_query,
        path=path,
        ref=ref,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    url_query: str,
    path: str | Unset = "/",
    ref: str | Unset = "master",
) -> RepoOwnersResponse | None:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Path modes:
    - \"/\" - Root OWNERS file only
    - \"/path\" - Specific path with inherited owners from parent directories

    Args:
        cache: Cache backend for VCS API responses
        url: Repository URL (e.g., https://github.com/openshift/osdctl)
        path: Path mode (/, /path, or ALL)
        ref: Git reference (branch, tag, commit SHA)

    Returns:
        RepoOwnersResponse with provider type, approvers, and reviewers lists

    Raises:
        HTTPException:
            - 500 Internal Server Error: If VCS API call fails or tokens not found

    Example:
        GET /api/v1/external/vcs/repos/owners?url=https://github.com/openshift/osdctl&path=/&ref=master
        Response:
        {
            \"provider\": \"github\",
            \"approvers\": [\"github_user1\", \"github_user2\"],
            \"reviewers\": [\"github_user3\"]
        }

    Args:
        url_query (str): Repository URL (e.g., https://github.com/owner/repo)
        path (str | Unset): Path mode: '/' (root OWNERS), '/path' (specific path with inheritance)
            Default: '/'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        RepoOwnersResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            url_query=url_query,
            path=path,
            ref=ref,
        )
    ).parsed
