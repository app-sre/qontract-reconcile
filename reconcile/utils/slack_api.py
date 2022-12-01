from __future__ import annotations

import json
import logging
from collections.abc import (
    Iterable,
    Mapping,
    Sequence,
)
from typing import (
    Any,
    Optional,
    Protocol,
    Union,
)

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import (
    HttpRequest,
    HttpResponse,
    RateLimitErrorRetryHandler,
    RetryHandler,
    RetryState,
)

MAX_RETRIES = 5
TIMEOUT = 30


class UserNotFoundException(Exception):
    pass


class UsergroupNotFoundException(Exception):
    pass


class ServerErrorRetryHandler(RetryHandler):
    """Retry handler for 5xx errors."""

    def _can_retry(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: Optional[HttpResponse] = None,
        error: Optional[Exception] = None,
    ) -> bool:
        return response is not None and response.status_code >= 500


class SupportsClientGlobalConfig(Protocol):
    max_retries: Optional[int]
    timeout: Optional[int]

    def dict(self) -> dict[str, Optional[int]]:
        ...


class SupportsClientMethodConfig(Protocol):
    name: str
    args: str  # Json

    def dict(self) -> dict[str, str]:
        ...


class SupportsClientConfig(Protocol):
    @property
    def q_global(self) -> Optional[SupportsClientGlobalConfig]:
        ...

    @property
    def methods(self) -> Optional[Sequence[SupportsClientMethodConfig]]:
        ...


class SlackApiConfig:
    """
    Aggregates Slack API configuration objects to be used passed to a
    SlackApi object.
    """

    def __init__(self, timeout: int = TIMEOUT, max_retries: int = MAX_RETRIES) -> None:

        self.timeout = timeout
        self.max_retries = max_retries
        self._methods: dict[str, Any] = {}

    def set_method_config(
        self, method_name: str, method_config: Mapping[str, Any]
    ) -> None:
        """
        Sets configuration for a Slack method.
        :param method_name: name of the method (ex. users.list)
        :param method_config: configuration for a specific method
        """
        self._methods[method_name] = method_config

    def get_method_config(self, method_name: str) -> Optional[dict[str, Any]]:
        """
        Get Slack method configuration.
        :param method_name: the name of a method (ex. users.list)
        """
        return self._methods.get(method_name)

    @classmethod
    def from_dict(cls, config_data: Mapping[str, Any]) -> SlackApiConfig:
        """
        Build a SlackApiConfig object from a mapping object.

        Input example:
            {
                'global': {
                    'max_retries': 5,
                    'timeout': 30
                },
                'methods': [
                    {'name': 'users.list', 'args': "{\"limit\":1000}"},
                    {'name': 'conversations.list', 'args': "{\"limit\":1000}"}
                ]
            }
        """
        kwargs = {}
        global_config = config_data.get("global", {})
        max_retries = global_config.get("max_retries")
        timeout = global_config.get("timeout")

        if max_retries:
            kwargs["max_retries"] = max_retries
        if timeout:
            kwargs["timeout"] = timeout

        config = cls(**kwargs)

        methods = config_data.get("methods", [])

        for method in methods:
            args = json.loads(method["args"])
            config.set_method_config(method["name"], args)

        return config

    @classmethod
    def from_client_config(cls, config_data: SupportsClientConfig) -> SlackApiConfig:
        """Initiate a SlackApiConfig instance via user-defined config class (e.g. GQL class).

        The config class must implement the `SupportsClientConfig` protocol.
        """
        config: dict[str, Union[list[dict[str, str]], dict[str, Optional[int]]]] = {}
        if config_data.q_global:
            config["global"] = config_data.q_global.dict()
        if config_data.methods:
            config["methods"] = [m.dict() for m in config_data.methods]
        return cls.from_dict(config)


class SlackApi:
    """Wrapper around Slack API calls"""

    def __init__(
        self,
        workspace_name: str,
        token: str,
        api_config: Optional[SlackApiConfig] = None,
        init_usergroups: bool = True,
        channel: Optional[str] = None,
        **chat_kwargs: Any,
    ) -> None:
        """
        :param workspace_name: Slack workspace name (ex. coreos)
        :param token: data to pass to SecretReader.read() to get the token
        :param secret_reader: secret reader to access slack credentials
        :param api_config: Slack API configuration
        :param init_usergroups: whether or not to get a list of all Slack
        usergroups when instantiated
        :param channel: the Slack channel to post messages to, only used
        when posting messages to a channel
        :param chat_kwargs: any other kwargs that can be used to post Slack
        channel messages
        """
        self.workspace_name = workspace_name

        if api_config:
            self.config = api_config
        else:
            self.config = SlackApiConfig()

        self._sc = WebClient(token=token, timeout=self.config.timeout)
        self._configure_client_retry()

        self._results: dict[str, Any] = {}

        self.channel = channel
        self.chat_kwargs = chat_kwargs

        if init_usergroups:
            self._initiate_usergroups()

    def _configure_client_retry(self) -> None:
        """
        Add retry handlers in addition to the defaults provided by the Slack
        client.
        """
        rate_limit_handler = RateLimitErrorRetryHandler(
            max_retry_count=self.config.max_retries
        )
        server_error_handler = ServerErrorRetryHandler(
            max_retry_count=self.config.max_retries
        )

        self._sc.retry_handlers.append(rate_limit_handler)
        self._sc.retry_handlers.append(server_error_handler)

    def chat_post_message(self, text: str) -> None:
        """
        Try to send a chat message into a channel. If the bot is not in the
        channel it will join the channel and send the message again.

        :param text: message to send to channel
        :raises ValueError: when Slack channel wasn't provided
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response
        from Slack API, except for not_in_channel
        """
        if not self.channel:
            raise ValueError(
                "Slack channel name must be provided when posting messages."
            )

        def do_send(c: str, t: str) -> None:
            self._sc.chat_postMessage(channel=c, text=t, **self.chat_kwargs)

        try:
            do_send(self.channel, text)
        except SlackApiError as e:
            if e.response["error"] == "not_in_channel":
                self.join_channel()
                do_send(self.channel, text)
            else:
                raise e

    def describe_usergroup(
        self, handle: str
    ) -> tuple[dict[str, str], dict[str, str], str]:
        usergroup = self.get_usergroup(handle)
        description = usergroup["description"]

        user_ids: list[str] = usergroup.get("users", [])
        users = self.get_users_by_ids(user_ids)

        channel_ids = usergroup["prefs"]["channels"]
        channels = self.get_channels_by_ids(channel_ids)

        return users, channels, description

    def join_channel(self) -> None:
        """
        Join a given channel if not already a member, will join self.channel

        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        :raises ValueError: if self.channel is not set
        """
        if not self.channel:
            raise ValueError(
                "Slack channel name must be provided when joining a channel."
            )

        channels_found = self.get_channels_by_names(self.channel)
        [channel_id] = [k for k in channels_found if channels_found[k] == self.channel]
        info = self._sc.conversations_info(channel=channel_id)
        if not info.data["channel"]["is_member"]:  # type: ignore[call-overload]
            self._sc.conversations_join(channel=channel_id)

    def get_usergroup_id(self, handle: str) -> Optional[str]:
        try:
            return self.get_usergroup(handle)["id"]
        except UsergroupNotFoundException:
            return None

    def _initiate_usergroups(self) -> None:
        """
        Initiates usergroups list.

        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        """
        result = self._sc.usergroups_list(include_users=True)
        self.usergroups = result["usergroups"]

    def get_usergroup(self, handle: str) -> dict[str, Any]:
        usergroup = [g for g in self.usergroups if g["handle"] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        return usergroup[0]

    def create_usergroup(self, handle: str) -> str:
        response = self._sc.usergroups_create(name=handle, handle=handle)
        return response["usergroup"]["id"]

    def update_usergroup(
        self, id: str, channels_list: Sequence[str], description: str
    ) -> None:
        """
        Update an existing usergroup.

        :param id: encoded usergroup ID
        :param channels_list: encoded channel IDs that the usergroup uses by
        default
        :param description: short description of the usergroup
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        """
        self._sc.usergroups_update(
            usergroup=id, channels=channels_list, description=description
        )

    def update_usergroup_users(self, id: str, users_list: Sequence[str]) -> None:
        """
        Update the list of users for a usergroup.

        :param id: encoded usergroup ID
        :param users_list: encoded user IDs that represents the entire list
        of users for the usergroup
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        """
        # since Slack API does not support empty usergroups
        # we can trick it by passing a deleted user
        if len(users_list) == 0:
            users_list = [self.get_random_deleted_user()]

        try:
            self._sc.usergroups_users_update(usergroup=id, users=users_list)
        except SlackApiError as e:
            # Slack can throw an invalid_users error when emptying groups, but
            # it will still empty the group (so this can be ignored).
            if e.response["error"] != "invalid_users":
                raise

    def get_random_deleted_user(self) -> str:
        for user_id, user_data in self._get("users").items():
            if user_data["deleted"] is True:
                return user_id

        logging.error(
            "could not find a deleted user, " + "empty usergroup will not work"
        )
        return ""

    def get_user_id_by_name(self, user_name: str, mail_address: str) -> str:
        """
        Get user id from their username.

        :param user_name: Slack user name
        :return: encoded user ID (ex. W012A3CDE)
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        :raises UserNotFoundException: if the Slack user is not found
        """
        try:
            result = self._sc.users_lookupByEmail(email=f"{user_name}@{mail_address}")
        except SlackApiError as e:
            if e.response["error"] == "users_not_found":
                raise UserNotFoundException(e.response["error"])
            else:
                raise

        return result["user"]["id"]

    def get_channels_by_names(self, channels_names: Iterable[str]) -> dict[str, str]:
        return {
            k: v["name"]
            for k, v in self._get("channels").items()
            if v["name"] in channels_names
        }

    def get_channels_by_ids(self, channels_ids: Iterable[str]) -> dict[str, str]:
        return {
            k: v["name"] for k, v in self._get("channels").items() if k in channels_ids
        }

    def get_users_by_names(self, user_names: Iterable[str]) -> dict[str, str]:
        return {
            k: v["name"]
            for k, v in self._get("users").items()
            if v["name"] in user_names
        }

    def get_users_by_ids(self, users_ids: Iterable[str]) -> dict[str, str]:
        return {k: v["name"] for k, v in self._get("users").items() if k in users_ids}

    def _get(self, resource: str) -> dict[str, Any]:
        """
        Get Slack resources by type. This method uses a cache to ensure that
        each resource type is only fetched once.

        :param resource: resource type
        :return: data from API call
        """
        result_key = "members" if resource == "users" else resource
        api_key = "conversations" if resource == "channels" else resource
        results = {}
        additional_kwargs: dict[str, Union[str, int]] = {"cursor": ""}

        if resource in self._results:
            return self._results[resource]

        method_config = self.config.get_method_config(f"{api_key}.list")
        if method_config:
            additional_kwargs.update(method_config)

        while True:
            result = self._sc.api_call(
                "{}.list".format(api_key), http_verb="GET", params=additional_kwargs
            )

            for r in result[result_key]:
                results[r["id"]] = r

            cursor = result["response_metadata"]["next_cursor"]

            if cursor == "":
                break

            additional_kwargs["cursor"] = cursor

        self._results[resource] = results
        return results
