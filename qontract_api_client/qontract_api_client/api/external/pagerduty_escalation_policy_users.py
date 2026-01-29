from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.escalation_policy_users_response import EscalationPolicyUsersResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    policy_id: str,
    *,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
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

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/external/pagerduty/escalation-policies/{policy_id}/users".format(
            policy_id=quote(str(policy_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EscalationPolicyUsersResponse:
    if response.status_code == 200:
        response_200 = EscalationPolicyUsersResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[EscalationPolicyUsersResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> Response[EscalationPolicyUsersResponse]:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        policy_id (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EscalationPolicyUsersResponse]
    """

    kwargs = _get_kwargs(
        policy_id=policy_id,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> EscalationPolicyUsersResponse:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        policy_id (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EscalationPolicyUsersResponse
    """

    parsed = sync_detailed(
        policy_id=policy_id,
        client=client,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> Response[EscalationPolicyUsersResponse]:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        policy_id (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EscalationPolicyUsersResponse]
    """

    kwargs = _get_kwargs(
        policy_id=policy_id,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> EscalationPolicyUsersResponse:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        policy_id (str):
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EscalationPolicyUsersResponse
    """

    parsed = (
        await asyncio_detailed(
            policy_id=policy_id,
            client=client,
            secret_manager_url=secret_manager_url,
            path=path,
            field=field,
            version=version,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
