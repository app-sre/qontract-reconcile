from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.schedule_users_response import ScheduleUsersResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    schedule_id: str,
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
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> Response[ScheduleUsersResponse]:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ScheduleUsersResponse]
    """

    kwargs = _get_kwargs(
        schedule_id=schedule_id,
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
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> ScheduleUsersResponse:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ScheduleUsersResponse
    """

    parsed = sync_detailed(
        schedule_id=schedule_id,
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
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> Response[ScheduleUsersResponse]:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ScheduleUsersResponse]
    """

    kwargs = _get_kwargs(
        schedule_id=schedule_id,
        secret_manager_url=secret_manager_url,
        path=path,
        field=field,
        version=version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    schedule_id: str,
    *,
    client: AuthenticatedClient | Client,
    secret_manager_url: str,
    path: str,
    field: None | str | Unset = UNSET,
    version: int | None | Unset = UNSET,
) -> ScheduleUsersResponse:
    r"""Get Schedule Users

     Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users

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
        secret_manager_url (str): Secret Manager URL
        path (str): Path to the secret
        field (None | str | Unset): Specific field within the secret
        version (int | None | Unset): Version of the secret

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
            secret_manager_url=secret_manager_url,
            path=path,
            field=field,
            version=version,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
