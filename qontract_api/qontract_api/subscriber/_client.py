"""qontract-api client initialization and Slack posting function."""

from qontract_api_client.client import client as qontract_api_client
from qontract_api_client.client import slack_chat_post_message as post_chat
from qontract_api_client.config import Config as QontractApiClientConfig
from qontract_api_client.schemas import ChatRequest, Secret

from qontract_api.config import settings
from qontract_api.logger import get_logger

logger = get_logger(__name__)

_client_configured = False


def _setup_client() -> None:
    """Configure the qontract-api client with the server URL and token from the config.

    Raises:
        RuntimeError: If subscriber settings not configured or token not set
    """
    global _client_configured  # noqa: PLW0603
    if _client_configured:
        return
    if not settings.subscriber.qontract_api_token:
        raise RuntimeError("settings.SubscriberSettings.qontract_api_token not set.")
    qontract_api_client.configure(
        config=QontractApiClientConfig(
            base_url=settings.subscriber.qontract_api_url,
            headers={
                "Authorization": f"Bearer {settings.subscriber.qontract_api_token}"
            },
            timeout=30,
        )
    )
    _client_configured = True


def _build_chat_request(
    text: str,
    *,
    channel: str | None = None,
    user: str | None = None,
) -> ChatRequest:
    """Build a ChatRequest with shared Secret and subscriber settings."""
    if settings.subscriber.slack_token is None:
        raise RuntimeError("Subscriber settings slack_token not configured!")
    return ChatRequest(
        workspace_name=settings.subscriber.slack_workspace,
        channel=channel,
        user=user,
        text=text,
        secret=Secret(
            path=settings.subscriber.slack_token.path,
            field=settings.subscriber.slack_token.field,
            version=settings.subscriber.slack_token.version,
            secret_manager_url=settings.secrets.default_provider_url,
        ),
        username=settings.subscriber.slack_username,
        icon_emoji=settings.subscriber.slack_icon_emoji,
    )


async def post_to_slack(message: str) -> None:
    """Post a message to Slack via qontract-api REST endpoint."""
    _setup_client()
    chat_request = _build_chat_request(
        message, channel=settings.subscriber.slack_channel
    )
    await post_chat(chat_request)
    logger.info(
        "Message posted to Slack via qontract-api",
        channel=settings.subscriber.slack_channel,
        workspace=settings.subscriber.slack_workspace,
    )


async def send_dm(org_username: str, text: str) -> None:
    """Send a DM to a user via qontract-api chat endpoint."""
    _setup_client()
    chat_request = _build_chat_request(text, user=org_username)
    await post_chat(chat_request)
    logger.info(
        "DM sent via qontract-api",
        user=org_username,
        workspace=settings.subscriber.slack_workspace,
    )
