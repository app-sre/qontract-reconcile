from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.repo_owners_response import RepoOwnersResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    owners_file: str | Unset = "/OWNERS",
    ref: str | Unset = "master",
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

    params["owners_file"] = owners_file

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
) -> RepoOwnersResponse:
    if response.status_code == 200:
        response_200 = RepoOwnersResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


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
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    owners_file: str | Unset = "/OWNERS",
    ref: str | Unset = "master",
) -> Response[RepoOwnersResponse]:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Args:
        params: VCSQueryParams with repo_url, owners_file, ref, and secret reference

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://github.com/owner/repo)
        owners_file (str | Unset): Path to OWNERS file in the repository (e.g., /OWNERS or
            /path/to/OWNERS) Default: '/OWNERS'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[RepoOwnersResponse]
    """

    kwargs = _get_kwargs(
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        owners_file=owners_file,
        ref=ref,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    owners_file: str | Unset = "/OWNERS",
    ref: str | Unset = "master",
) -> RepoOwnersResponse:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Args:
        params: VCSQueryParams with repo_url, owners_file, ref, and secret reference

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://github.com/owner/repo)
        owners_file (str | Unset): Path to OWNERS file in the repository (e.g., /OWNERS or
            /path/to/OWNERS) Default: '/OWNERS'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        RepoOwnersResponse
    """

    parsed = sync_detailed(
        client=client,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        owners_file=owners_file,
        ref=ref,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    owners_file: str | Unset = "/OWNERS",
    ref: str | Unset = "master",
) -> Response[RepoOwnersResponse]:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Args:
        params: VCSQueryParams with repo_url, owners_file, ref, and secret reference

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://github.com/owner/repo)
        owners_file (str | Unset): Path to OWNERS file in the repository (e.g., /OWNERS or
            /path/to/OWNERS) Default: '/OWNERS'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[RepoOwnersResponse]
    """

    kwargs = _get_kwargs(
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        repo_url=repo_url,
        owners_file=owners_file,
        ref=ref,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    repo_url: str,
    owners_file: str | Unset = "/OWNERS",
    ref: str | Unset = "master",
) -> RepoOwnersResponse:
    r"""Get Repo Owners

     Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Args:
        params: VCSQueryParams with repo_url, owners_file, ref, and secret reference

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        repo_url (str): Repository URL (e.g., https://github.com/owner/repo)
        owners_file (str | Unset): Path to OWNERS file in the repository (e.g., /OWNERS or
            /path/to/OWNERS) Default: '/OWNERS'.
        ref (str | Unset): Git reference (branch, tag, commit SHA) Default: 'master'.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        RepoOwnersResponse
    """

    parsed = (
        await asyncio_detailed(
            client=client,
            secret_manager_url=secret_manager_url,
            path=path,
            field=field,
            version=version,
            repo_url=repo_url,
            owners_file=owners_file,
            ref=ref,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
