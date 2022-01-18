import json
import logging
from typing import Sequence, Dict, Any, Mapping, Optional, Union, ItemsView, \
    Iterable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import RateLimitErrorRetryHandler, RetryHandler, \
    RetryState, HttpRequest, HttpResponse

from reconcile.utils.secret_reader import SecretReader


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
            error: Optional[Exception] = None
    ) -> bool:
        return response is not None and response.status_code >= 500


class SlackApiConfig:
    """
    Aggregates Slack API configuration objects to be used passed to a
    SlackApi object.
    """
    MAX_RETRIES = 5
    TIMEOUT = 30

    def __init__(self,
                 timeout: int = TIMEOUT,
                 max_retries: int = MAX_RETRIES) -> None:

        self.timeout = timeout
        self.max_retries = max_retries
        self._methods: Dict[str, Any] = {}

    def set_method_config(self,
                          method_name: str,
                          method_config: Mapping[str, Any]
                          ) -> None:
        """
        Sets configuration for a Slack method.
        :param method_name: name of the method (ex. users.list)
        :param method_config: configuration for a specific method
        """
        self._methods[method_name] = method_config

    def get_method_config(self, method_name: str) -> Optional[Dict[str, Any]]:
        """
        Get Slack method configuration.
        :param method_name: the name of a method (ex. users.list)
        """
        return self._methods.get(method_name)

    @classmethod
    def from_dict(cls, config_data: Mapping[str, Any]) -> "SlackApiConfig":
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
        global_config = config_data.get('global', {})
        max_retries = global_config.get('max_retries')
        timeout = global_config.get('timeout')

        if max_retries:
            kwargs['max_retries'] = max_retries
        if timeout:
            kwargs['timeout'] = timeout

        config = cls(**kwargs)

        methods = config_data.get('methods', [])

        for method in methods:
            args = json.loads(method['args'])
            config.set_method_config(method['name'], args)

        return config


class SlackApi:
    """Wrapper around Slack API calls"""

    RESOURCE_GET_CONVERSATIONS = 'conversations'
    RESOURCE_GET_USERS = 'users'
    RESOURCE_GET_USERGROUPS = 'usergroups'
    RESOURCE_GET_RESULT_KEYS = {
        RESOURCE_GET_CONVERSATIONS: 'channels',
        RESOURCE_GET_USERS: 'members',
        RESOURCE_GET_USERGROUPS: 'usergroups'
    }

    def __init__(self,
                 workspace_name: str,
                 token: Mapping[str, str],
                 api_config: Optional[SlackApiConfig] = None,
                 secret_reader_settings: Optional[Mapping[str, Any]] = None,
                 channel: Optional[str] = None,
                 icon_emoji: Optional[str] = None,
                 username: Optional[str] = None) -> None:
        """
        :param workspace_name: Slack workspace name (ex. coreos)
        :param token: data to pass to SecretReader.read() to get the token
        :param api_config: Slack API configuration
        :param secret_reader_settings: settings to pass to SecretReader
        :param channel: the Slack channel to post messages to, only
        used when posting messages to a channel
        """
        self._cached_results: Dict[str, Any] = {}
        self.workspace_name = workspace_name
        self.channel = channel

        self.icon_emoji = icon_emoji
        self.username = username

        secret_reader = SecretReader(settings=secret_reader_settings)
        slack_token = secret_reader.read(token)

        if api_config:
            self.api_config = api_config
        else:
            self.api_config = SlackApiConfig()

        # mandatory for client to work, do not move to app-interface
        self.api_config.set_method_config(
            f'{self.RESOURCE_GET_USERGROUPS}.list', {'include_users': True})

        self._sc = WebClient(token=slack_token,
                             timeout=self.api_config.timeout)

        self._sc.retry_handlers.append(RateLimitErrorRetryHandler(
            max_retry_count=self.api_config.max_retries))
        self._sc.retry_handlers.append(ServerErrorRetryHandler(
            max_retry_count=self.api_config.max_retries))

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
            raise ValueError('Slack channel name must be provided when '
                             'posting messages.')

        def do_send(c: str, t: str):
            self._sc.chat_postMessage(channel=c, text=t,
                                      username=self.username,
                                      icon_emoji=self.icon_emoji)

        try:
            do_send(self.channel, text)
        except SlackApiError as e:
            if e.response['error'] == "not_in_channel":
                self.join_channel()
                do_send(self.channel, text)
            else:
                raise e

    def describe_usergroup(self, handle):
        usergroup = self.get_usergroup(handle)
        description = usergroup['description']

        user_ids = usergroup.get('users', [])
        users = self.get_users_by_ids(user_ids)

        channel_ids = usergroup['prefs']['channels']
        channels = self.get_channels_by_ids(channel_ids)

        return users, channels, description

    def join_channel(self):
        """
        Join a given channel if not already a member, will join self.channel

        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        :raises ValueError: if self.channel is not set
        """
        if not self.channel:
            raise ValueError('Slack channel name must be provided when '
                             'joining a channel.')

        channels_found = self.get_channels_by_names(self.channel)
        [channel_id] = [k for k in channels_found if
                        channels_found[k] == self.channel]
        info = self._sc.conversations_info(channel=channel_id)
        if not info.data['channel']['is_member']:
            self._sc.conversations_join(channel=channel_id)

    def get_usergroup_id(self, handle):
        usergroup = self.get_usergroup(handle)
        return usergroup['id']

    def get_usergroup(self, handle):
        groups = self._resource_get_or_cached(self.RESOURCE_GET_USERGROUPS)
        usergroup = [g for g in groups if groups[g]['handle'] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        return groups[usergroup[0]]

    def update_usergroup(self, id: str, channels_list: Sequence[str],
                         description: str) -> None:
        # TODO: Add test
        """
        Update an existing usergroup.

        :param id: encoded usergroup ID
        :param channels_list: encoded channel IDs that the usergroup uses by
        default
        :param description: short description of the usergroup
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        """
        self._sc.usergroups_update(usergroup=id, channels=channels_list,
                                   description=description)
        self._cache_invalidate(self.RESOURCE_GET_USERGROUPS)

    def update_usergroup_users(self, id: str,
                               users_list: Sequence[str]) -> None:
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
            self._cache_invalidate(self.RESOURCE_GET_USERGROUPS)
        except SlackApiError as e:
            # Slack can throw an invalid_users error when emptying groups, but
            # it will still empty the group (so this can be ignored).
            if e.response['error'] != 'invalid_users':
                raise

    def get_random_deleted_user(self):
        for user_id, user_data in self._get_users():
            if user_data['deleted'] is True:
                return user_id

        logging.error('could not find a deleted user, ' +
                      'empty usergroup will not work')
        return ''

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
            result = self._sc.users_lookupByEmail(
                email=f"{user_name}@{mail_address}"
            )
        except SlackApiError as e:
            if e.response['error'] == 'users_not_found':
                raise UserNotFoundException(e.response['error'])
            else:
                raise

        return result['user']['id']

    def get_channels_by_names(self, channels_names: Iterable[str]) \
            -> Dict[str, str]:
        return {k: v['name'] for k, v in self._get_channels()
                if v['name'] in channels_names}

    def get_channels_by_ids(self, channels_ids: Iterable[str]) \
            -> Dict[str, str]:
        return {k: v['name'] for k, v in self._get_channels()
                if k in channels_ids}

    def get_users_by_names(self, user_names: Iterable[str]) -> Dict[str, str]:
        return {k: v['name'] for k, v in self._get_users()
                if v['name'] in user_names}

    def get_users_by_ids(self, users_ids: Iterable[str]) -> Dict[str, str]:
        return {k: v['name'] for k, v in self._get_users()
                if k in users_ids}

    def _get_channels(self) -> ItemsView:
        return self._resource_get_or_cached(
            self.RESOURCE_GET_CONVERSATIONS).items()

    def _get_users(self) -> ItemsView:
        return self._resource_get_or_cached(self.RESOURCE_GET_USERS).items()

    def _cache_invalidate(self, resource: str):
        if resource in self._cached_results:
            del self._cached_results[resource]

    def _resource_get_or_cached(self, resource: str) -> Dict[str, Any]:
        """
         Get Slack resources by type. This method uses a cache to ensure that
         each resource type is only fetched once.

         :param resource: resource type
         :return: data from API call
         """

        if resource in self._cached_results:
            return self._cached_results[resource]

        additional_kwargs: Dict[str, Union[str, int, bool]] = {'cursor': ''}
        if self.api_config:
            method_config = self.api_config.get_method_config(
                f'{resource}.list')

        if method_config:
            additional_kwargs.update(method_config)

        self._cached_results[resource] = self._paginated_get(resource,
                                                             additional_kwargs)

        return self._cached_results[resource]

    def _paginated_get(self, resource: str,
                       additional_kwargs: Dict[str, Union[str, int, bool]]) \
            -> Dict[str, Any]:
        if resource not in self.RESOURCE_GET_RESULT_KEYS:
            result_key = resource
        else:
            result_key = self.RESOURCE_GET_RESULT_KEYS[resource]

        resource_results: Dict[str, Any] = {}
        while True:
            result = self._sc.api_call(
                "{}.list".format(resource),
                http_verb='GET',
                params=additional_kwargs
            )

            for r in result[result_key]:
                resource_results[r['id']] = r

            cursor = None
            if 'response_metadata' in result:
                cursor = result['response_metadata']['next_cursor']

            if cursor is None or cursor == '':
                break

            additional_kwargs['cursor'] = cursor
        return resource_results
