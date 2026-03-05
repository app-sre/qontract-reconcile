from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.chat_request import ChatRequest
from ...models.chat_response import ChatResponse
from ...types import Response


def _get_kwargs(
    *,
    body: ChatRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/v1/external/slack/chat",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ChatResponse:
    if response.status_code == 200:
        response_200 = ChatResponse.from_dict(response.json())

        return response_200

    raise errors.UnexpectedStatus(response.status_code, response.content)


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ChatResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ChatRequest,
) -> Response[ChatResponse]:
    """Post Chat

     Post a message to a Slack channel.

    Sends a chat message to the specified channel in the given workspace.
    Supports threaded replies via thread_ts.

    Args:
        request: Chat request with channel, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 502 Bad Gateway: If Slack API call fails

    Args:
        body (ChatRequest): Request model for posting a Slack message.

            Immutable model with all fields required to send a chat message.

            Attributes:
                workspace_name: Slack workspace name
                channel: Channel name to post to
                text: Message text
                thread_ts: Optional thread timestamp for replies
                icon_emoji: Emoji to use as the message icon
                icon_url: URL to an image to use as the message icon
                username: Bot username to display
                secret: Secret reference for Slack bot token

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ChatResponse]
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
    body: ChatRequest,
) -> ChatResponse:
    """Post Chat

     Post a message to a Slack channel.

    Sends a chat message to the specified channel in the given workspace.
    Supports threaded replies via thread_ts.

    Args:
        request: Chat request with channel, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 502 Bad Gateway: If Slack API call fails

    Args:
        body (ChatRequest): Request model for posting a Slack message.

            Immutable model with all fields required to send a chat message.

            Attributes:
                workspace_name: Slack workspace name
                channel: Channel name to post to
                text: Message text
                thread_ts: Optional thread timestamp for replies
                icon_emoji: Emoji to use as the message icon
                icon_url: URL to an image to use as the message icon
                username: Bot username to display
                secret: Secret reference for Slack bot token

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ChatResponse
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
    body: ChatRequest,
) -> Response[ChatResponse]:
    """Post Chat

     Post a message to a Slack channel.

    Sends a chat message to the specified channel in the given workspace.
    Supports threaded replies via thread_ts.

    Args:
        request: Chat request with channel, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 502 Bad Gateway: If Slack API call fails

    Args:
        body (ChatRequest): Request model for posting a Slack message.

            Immutable model with all fields required to send a chat message.

            Attributes:
                workspace_name: Slack workspace name
                channel: Channel name to post to
                text: Message text
                thread_ts: Optional thread timestamp for replies
                icon_emoji: Emoji to use as the message icon
                icon_url: URL to an image to use as the message icon
                username: Bot username to display
                secret: Secret reference for Slack bot token

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ChatResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ChatRequest,
) -> ChatResponse:
    """Post Chat

     Post a message to a Slack channel.

    Sends a chat message to the specified channel in the given workspace.
    Supports threaded replies via thread_ts.

    Args:
        request: Chat request with channel, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 502 Bad Gateway: If Slack API call fails

    Args:
        body (ChatRequest): Request model for posting a Slack message.

            Immutable model with all fields required to send a chat message.

            Attributes:
                workspace_name: Slack workspace name
                channel: Channel name to post to
                text: Message text
                thread_ts: Optional thread timestamp for replies
                icon_emoji: Emoji to use as the message icon
                icon_url: URL to an image to use as the message icon
                username: Bot username to display
                secret: Secret reference for Slack bot token

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ChatResponse
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
