"""Factory for creating SlackWorkspaceClient instances with rate limiting.

Follows the PagerDuty factory pattern: function-based factory with Secret resolution.
"""

from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, Hooks
from qontract_utils.secret_reader import Secret
from qontract_utils.slack_api import SlackApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.secret_manager import SecretManager
from qontract_api.slack.slack_workspace_client import SlackWorkspaceClient


def create_slack_workspace_client(
    secret: Secret,
    workspace_name: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> SlackWorkspaceClient:
    """Create SlackWorkspaceClient with credentials from Vault.

    Follows the PagerDuty factory pattern: caller provides Secret reference,
    factory resolves token via SecretManager internally.

    Args:
        secret: Secret reference for Slack API token (resolved via SecretManager)
        workspace_name: Slack workspace name
        cache: Cache backend for distributed caching and locking
        secret_manager: Secret backend for retrieving tokens from Vault
        settings: Application settings with Slack configuration

    Returns:
        SlackWorkspaceClient instance with full caching + compute layer
    """
    token = secret_manager.read(secret)

    slack_api = SlackApi(
        slack_api_url=settings.slack.api_url,
        workspace_name=workspace_name,
        token=token,
        timeout=settings.slack.api_timeout,
        max_retries=settings.slack.api_max_retries,
        method_configs=settings.slack.api_method_configs,
        hooks=Hooks(retry_config=DEFAULT_RETRY_CONFIG),
    )

    return SlackWorkspaceClient(
        slack_api=slack_api,
        cache=cache,
        settings=settings,
    )
