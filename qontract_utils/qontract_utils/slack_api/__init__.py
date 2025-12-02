"""Slack API client and models."""

from slack_sdk.errors import SlackApiError

from qontract_utils.slack_api.client import (
    SlackApi,
    SlackApiCallContext,
    UsergroupNotFoundError,
    UserNotFoundError,
)
from qontract_utils.slack_api.models import (
    SlackChannel,
    SlackEnterpriseUser,
    SlackUser,
    SlackUsergroup,
    SlackUsergroupPrefs,
    SlackUserProfile,
)

__all__ = [
    "SlackApi",
    "SlackApiCallContext",
    "SlackApiError",
    "SlackChannel",
    "SlackEnterpriseUser",
    "SlackUser",
    "SlackUserProfile",
    "SlackUsergroup",
    "SlackUsergroupPrefs",
    "UserNotFoundError",
    "UsergroupNotFoundError",
]
