from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.schedule_users_response import ScheduleUsersResponse
from ...types import UNSET, Response


def _get_kwargs(
    schedule_id: str,
    *,
    instance: str,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["instance"] = instance

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/external/pagerduty/schedules/{schedule_id}/users".format(
            schedule_id=quote(str(schedule_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ScheduleUsersResponse:
    if response.status_code == 200:
        response_200 = ScheduleUsersResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ScheduleUsersResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> Response[ScheduleUsersResponse]:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        schedule_id (str):
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ScheduleUsersResponse]
    """

    kwargs = _get_kwargs(
        schedule_id=schedule_id,
        instance=instance,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> ScheduleUsersResponse:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        schedule_id (str):
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ScheduleUsersResponse
    """

    parsed = sync_detailed(
        schedule_id=schedule_id,
        client=client,
        instance=instance,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> Response[ScheduleUsersResponse]:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        schedule_id (str):
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ScheduleUsersResponse]
    """

    kwargs = _get_kwargs(
        schedule_id=schedule_id,
        instance=instance,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    instance: str,
) -> ScheduleUsersResponse:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        cache: Cache backend for PagerDuty API responses
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            \"users\": [
                {\"username\": \"jsmith\"},
                {\"username\": \"mdoe\"}
            ]
        }

    Args:
        schedule_id (str):
        instance (str): PagerDuty instance name (e.g., 'app-sre')

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ScheduleUsersResponse
    """

    parsed = (
        await asyncio_detailed(
            schedule_id=schedule_id,
            client=client,
            instance=instance,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
