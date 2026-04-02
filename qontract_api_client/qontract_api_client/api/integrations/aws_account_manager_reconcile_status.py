from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.reconcile_result import ReconcileResult
from ...types import UNSET, Response, Unset


def _get_kwargs(
    task_id: str,
    *,
    timeout: int | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_timeout: int | None | Unset
    if isinstance(timeout, Unset):
        json_timeout = UNSET
    else:
        json_timeout = timeout
    params["timeout"] = json_timeout

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/v1/integrations/aws-account-manager/reconcile/{task_id}".format(
            task_id=quote(str(task_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ReconcileResult:
    if response.status_code == 200:
        response_200 = ReconcileResult.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ReconcileResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> Response[ReconcileResult]:
    """Aws Account Manager Reconcile Status

     Retrieve reconciliation task result.

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ReconcileResult]
    """

    kwargs = _get_kwargs(
        task_id=task_id,
        timeout=timeout,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> ReconcileResult:
    """Aws Account Manager Reconcile Status

     Retrieve reconciliation task result.

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ReconcileResult
    """

    parsed = sync_detailed(
        task_id=task_id,
        client=client,
        timeout=timeout,
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed


async def asyncio_detailed(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> Response[ReconcileResult]:
    """Aws Account Manager Reconcile Status

     Retrieve reconciliation task result.

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ReconcileResult]
    """

    kwargs = _get_kwargs(
        task_id=task_id,
        timeout=timeout,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    task_id: str,
    *,
    client: AuthenticatedClient,
    timeout: int | None | Unset = UNSET,
) -> ReconcileResult:
    """Aws Account Manager Reconcile Status

     Retrieve reconciliation task result.

    Args:
        task_id (str):
        timeout (int | None | Unset): Optional: Block up to N seconds for completion.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ReconcileResult
    """

    parsed = (
        await asyncio_detailed(
            task_id=task_id,
            client=client,
            timeout=timeout,
        )
    ).parsed
    if parsed is None:
        raise TypeError("Expected parsed response to be not None")
    return parsed
