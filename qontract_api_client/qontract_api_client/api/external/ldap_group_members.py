from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.ldap_group_members_response import LdapGroupMembersResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    group_name: str,
    *,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    base_url: str,
    token_url: str,
    client_id: str,
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

    params["base_url"] = base_url

    params["token_url"] = token_url

    params["client_id"] = client_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/external/ldap/groups/{group_name}/members".format(
            group_name=quote(str(group_name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> LdapGroupMembersResponse:
    if response.status_code == 200:
        response_200 = LdapGroupMembersResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[LdapGroupMembersResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    group_name: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    base_url: str,
    token_url: str,
    client_id: str,
) -> Response[LdapGroupMembersResponse]:
    """Get Group Members

     Get members of an LDAP group.

    Fetches members from the internal groups proxy API using OAuth2
    client-credentials authentication. Results are cached for performance.

    Args:
        group_name: LDAP group name
        cache: Cache dependency
        secret_manager: Secret manager dependency
        secret: LdapSecret with OAuth2 connection details and client_secret reference

    Returns:
        LdapGroupMembersResponse with list of group members

    Raises:
        HTTPException:
            - 500 Internal Server Error: If the internal groups API call fails

    Args:
        group_name (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        base_url (str): Base URL of the internal groups API
        token_url (str): OAuth2 token endpoint URL
        client_id (str): OAuth2 client ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[LdapGroupMembersResponse]
    """

    kwargs = _get_kwargs(
        group_name=group_name,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    group_name: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    base_url: str,
    token_url: str,
    client_id: str,
) -> LdapGroupMembersResponse:
    """Get Group Members

     Get members of an LDAP group.

    Fetches members from the internal groups proxy API using OAuth2
    client-credentials authentication. Results are cached for performance.

    Args:
        group_name: LDAP group name
        cache: Cache dependency
        secret_manager: Secret manager dependency
        secret: LdapSecret with OAuth2 connection details and client_secret reference

    Returns:
        LdapGroupMembersResponse with list of group members

    Raises:
        HTTPException:
            - 500 Internal Server Error: If the internal groups API call fails

    Args:
        group_name (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        base_url (str): Base URL of the internal groups API
        token_url (str): OAuth2 token endpoint URL
        client_id (str): OAuth2 client ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        LdapGroupMembersResponse
    """

    parsed = sync_detailed(
        group_name=group_name,
        client=client,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    group_name: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    base_url: str,
    token_url: str,
    client_id: str,
) -> Response[LdapGroupMembersResponse]:
    """Get Group Members

     Get members of an LDAP group.

    Fetches members from the internal groups proxy API using OAuth2
    client-credentials authentication. Results are cached for performance.

    Args:
        group_name: LDAP group name
        cache: Cache dependency
        secret_manager: Secret manager dependency
        secret: LdapSecret with OAuth2 connection details and client_secret reference

    Returns:
        LdapGroupMembersResponse with list of group members

    Raises:
        HTTPException:
            - 500 Internal Server Error: If the internal groups API call fails

    Args:
        group_name (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        base_url (str): Base URL of the internal groups API
        token_url (str): OAuth2 token endpoint URL
        client_id (str): OAuth2 client ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[LdapGroupMembersResponse]
    """

    kwargs = _get_kwargs(
        group_name=group_name,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    group_name: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
    base_url: str,
    token_url: str,
    client_id: str,
) -> LdapGroupMembersResponse:
    """Get Group Members

     Get members of an LDAP group.

    Fetches members from the internal groups proxy API using OAuth2
    client-credentials authentication. Results are cached for performance.

    Args:
        group_name: LDAP group name
        cache: Cache dependency
        secret_manager: Secret manager dependency
        secret: LdapSecret with OAuth2 connection details and client_secret reference

    Returns:
        LdapGroupMembersResponse with list of group members

    Raises:
        HTTPException:
            - 500 Internal Server Error: If the internal groups API call fails

    Args:
        group_name (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret
        base_url (str): Base URL of the internal groups API
        token_url (str): OAuth2 token endpoint URL
        client_id (str): OAuth2 client ID

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        LdapGroupMembersResponse
    """

    parsed = (
        await asyncio_detailed(
            group_name=group_name,
            client=client,
            secret_manager_url=secret_manager_url,
            path=path,
            field=field,
            version=version,
            base_url=base_url,
            token_url=token_url,
            client_id=client_id,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
