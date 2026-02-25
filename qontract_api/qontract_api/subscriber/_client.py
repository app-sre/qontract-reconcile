"""qontract-api client initialization and Slack posting function."""

from qontract_api_client.api.external.slack_chat_post_message import (
    asyncio as post_chat,
)
from qontract_api_client.client import AuthenticatedClient
from qontract_api_client.models.chat_request import ChatRequest
from qontract_api_client.models.secret import Secret

from qontract_api.config import settings
from qontract_api.logger import get_logger

logger = get_logger(__name__)


def _get_client() -> AuthenticatedClient:
    """Create authenticated qontract-api client.

    Returns:
        AuthenticatedClient configured with base URL and auth token

    Raises:
        RuntimeError: If subscriber settings not configured or token not set
    """
    if not settings.subscriber.qontract_api_token:
        raise RuntimeError("settings.SubscriberSettings.qontract_api_token not set.")

    return AuthenticatedClient(
        base_url=settings.subscriber.qontract_api_url,
        token=settings.subscriber.qontract_api_token,
    )


async def post_to_slack(message: str) -> None:
    """Post a message to Slack via qontract-api REST endpoint.

    Args:
        message: Formatted message text to post

    Raises:
        RuntimeError: If subscriber settings not configured
        httpx.HTTPError: If API call fails
    """
    if settings.subscriber.slack_token is None:
        raise RuntimeError("Subscriber settings slack_token not configured!")

    # Build chat request with secret reference for Slack bot token
    chat_request = ChatRequest(
        workspace_name=settings.subscriber.slack_workspace,
        channel=settings.subscriber.slack_channel,
        text=message,
        secret=Secret(
            path=settings.subscriber.slack_token.path,
            field=settings.subscriber.slack_token.field,
            version=settings.subscriber.slack_token.version,
            secret_manager_url=settings.secrets.default_provider_url,
        ),
    )

    # Call qontract-api REST endpoint
    client = _get_client()
    await post_chat(client=client, body=chat_request)

    logger.info(
        "Message posted to Slack via qontract-api",
        channel=settings.subscriber.slack_channel,
        workspace=settings.subscriber.slack_workspace,
    )
