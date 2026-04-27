from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.ldap_users_check_request import LdapUsersCheckRequest
from ...models.ldap_users_check_response import LdapUsersCheckResponse
from ...types import Response


def _get_kwargs(
    *,
    body: LdapUsersCheckRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/external/ldap/users/check",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> LdapUsersCheckResponse:
    if response.status_code == 200:
        response_200 = LdapUsersCheckResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[LdapUsersCheckResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: LdapUsersCheckRequest,
) -> Response[LdapUsersCheckResponse]:
    """Check Users Exist

     Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username

    Args:
        body (LdapUsersCheckRequest): Request to check which usernames exist in LDAP.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[LdapUsersCheckResponse]
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
    body: LdapUsersCheckRequest,
) -> LdapUsersCheckResponse:
    """Check Users Exist

     Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username

    Args:
        body (LdapUsersCheckRequest): Request to check which usernames exist in LDAP.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        LdapUsersCheckResponse
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
    body: LdapUsersCheckRequest,
) -> Response[LdapUsersCheckResponse]:
    """Check Users Exist

     Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username

    Args:
        body (LdapUsersCheckRequest): Request to check which usernames exist in LDAP.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[LdapUsersCheckResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: LdapUsersCheckRequest,
) -> LdapUsersCheckResponse:
    """Check Users Exist

     Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username

    Args:
        body (LdapUsersCheckRequest): Request to check which usernames exist in LDAP.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        LdapUsersCheckResponse
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
