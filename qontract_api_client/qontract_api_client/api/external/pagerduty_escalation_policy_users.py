from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.escalation_policy_users_response import EscalationPolicyUsersResponse
from ...types import UNSET, Response


def _get_kwargs(
    policy_id: str,
    *,
    instance: str,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["instance"] = instance

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": f"/api/v1/external/pagerduty/escalation-policies/{policy_id}/users",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EscalationPolicyUsersResponse | None:
    if response.status_code == 200:
        response_200 = EscalationPolicyUsersResponse.from_dict(response.json())

        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


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
    instance: str,
) -> Response[EscalationPolicyUsersResponse]:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users (username is org_username)

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
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EscalationPolicyUsersResponse]
    """

    kwargs = _get_kwargs(
        policy_id=policy_id,
        instance=instance,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> EscalationPolicyUsersResponse | None:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users (username is org_username)

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
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EscalationPolicyUsersResponse
    """

    return sync_detailed(
        policy_id=policy_id,
        client=client,
        instance=instance,
    ).parsed


async def asyncio_detailed(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> Response[EscalationPolicyUsersResponse]:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users (username is org_username)

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
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EscalationPolicyUsersResponse]
    """

    kwargs = _get_kwargs(
        policy_id=policy_id,
        instance=instance,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    policy_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> EscalationPolicyUsersResponse | None:
    r"""Get Escalation Policy Users

     Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users (username is org_username)

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
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EscalationPolicyUsersResponse
    """

    return (
        await asyncio_detailed(
            policy_id=policy_id,
            client=client,
            instance=instance,
        )
    ).parsed
