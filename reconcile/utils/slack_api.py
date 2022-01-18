import json
import logging
from typing import Sequence, Dict, Any, Mapping, Optional, Union

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import RateLimitErrorRetryHandler, RetryHandler, \
    RetryState, HttpRequest, HttpResponse

from reconcile import queries
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.config import get_config

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
            error: Optional[Exception] = None
    ) -> bool:
        return response is not None and response.status_code >= 500


class SlackApiConfig:
    """
    Aggregates Slack API configuration objects to be used passed to a
    SlackApi object.
    """

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

    RESOURCE_GET_CHANNELS = 'channels'
    RESOURCE_GET_USERS = 'users'

    def __init__(self,
                 workspace_name: str,
                 token: Mapping[str, str],
                 api_config: Optional[SlackApiConfig] = None,
                 secret_reader_settings: Optional[Mapping[str, Any]] = None,
                 init_usergroups=True,
                 channel: Optional[str] = None,
                 **chat_kwargs) -> None:
        """
        :param workspace_name: Slack workspace name (ex. coreos)
        :param token: data to pass to SecretReader.read() to get the token
        :param api_config: Slack API configuration
        :param secret_reader_settings: settings to pass to SecretReader
        :param init_usergroups: whether or not to get a list of all Slack
        :param join_on_init: whether or not to join chanel on init
        usergroups when instantiated
        :param channel: the Slack channel to post messages to, only
        used when posting messages to a channel
        :param chat_kwargs: any other kwargs that can be used to post Slack
        channel messages
        """
        self.workspace_name = workspace_name

        if api_config:
            self.api_config = api_config
        else:
            self.api_config = SlackApiConfig()

        secret_reader = SecretReader(settings=secret_reader_settings)
        slack_token = secret_reader.read(token)

        self._sc = WebClient(token=slack_token,
                             timeout=self.api_config.timeout)
        self._configure_client_retry()

        self._results: Dict[str, Any] = {}

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
            max_retry_count=self.api_config.max_retries)
        server_error_handler = ServerErrorRetryHandler(
            max_retry_count=self.api_config.max_retries)

        self._sc.retry_handlers.append(rate_limit_handler)
        self._sc.retry_handlers.append(server_error_handler)

    def chat_post_message(self, text: str) -> None:
        """
        Sends a message to a channel.

        :param text: message to send to channel
        :raises ValueError: when Slack channel wasn't provided
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response
        from Slack API
        """

        if not self.channel:
            raise ValueError('Slack channel name must be provided when '
                             'posting messages.')

        self._sc.chat_postMessage(channel=self.channel, text=text,
                                  **self.chat_kwargs)

    def describe_usergroup(self, handle):
        usergroup = self.get_usergroup(handle)
        description = usergroup['description']

        user_ids = usergroup.get('users', [])
        users = self.get_users_by_ids(user_ids)

        channel_ids = usergroup['prefs']['channels']
        channels = self.get_channels_by_ids(channel_ids)

        return users, channels, description

    def get_usergroup_id(self, handle):
        usergroup = self.get_usergroup(handle)
        return usergroup['id']

    def _initiate_usergroups(self) -> None:
        """
        Initiates usergroups list.

        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        """
        result = self._sc.usergroups_list(include_users=True)
        self.usergroups = result['usergroups']

    def get_usergroup(self, handle):
        usergroup = [g for g in self.usergroups if g['handle'] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        [usergroup] = usergroup
        return usergroup

    def update_usergroup(self, id: str, channels_list: Sequence[str],
                         description: str) -> None:
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
        except SlackApiError as e:
            # Slack can throw an invalid_users error when emptying groups, but
            # it will still empty the group (so this can be ignored).
            if e.response['error'] != 'invalid_users':
                raise

    def get_random_deleted_user(self):
        for user_id, user_data in self.get_users():
            if user_data['deleted'] is True:
                return user_id

        logging.error('could not find a deleted user, ' +
                      'empty usergroup will not work')
        return ''

    def get_user_id_by_name(self, user_name: str) -> str:
        """
        Get user id from their username.

        :param user_name: Slack user name
        :return: encoded user ID (ex. W012A3CDE)
        :raises slack_sdk.errors.SlackApiError: if unsuccessful response from
        Slack API
        :raises UserNotFoundException: if the Slack user is not found
        """
        config = get_config()
        mail_address = config['smtp']['mail_address']

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

    def get_channels_by_names(self, channels_names):
        return {k: v['name'] for k, v in self.get_channels()
                if v['name'] in channels_names}

    def get_channels_by_ids(self, channels_ids):
        return {k: v['name'] for k, v in self.get_channels()
                if k in channels_ids}

    def get_users_by_names(self, user_names):
        return {k: v['name'] for k, v in self.get_users()
                if v['name'] in user_names}

    def get_users_by_ids(self, users_ids):
        return {k: v['name'] for k, v in self.get_users()
                if k in users_ids}

    def get_channels(self):
        return self._get(self.RESOURCE_GET_CHANNELS).items()

    def get_users(self):
        return self._get(self.RESOURCE_GET_USERS).items()

    def _get(self, resource: str) -> Dict[str, Any]:
        """
        Get Slack resources by type. This method uses a cache to ensure that
        each resource type is only fetched once.

        :param resource: resource type
        :return: data from API call
        """
        result_key = 'members' if resource == 'users' else resource
        api_key = 'conversations' if resource == 'channels' else resource
        results = {}
        additional_kwargs: Dict[str, Union[str, int]] = {'cursor': ''}

        if resource in self._results:
            return self._results[resource]

        if self.api_config:
            method_config = self.api_config.get_method_config(
                f'{api_key}.list')
            if method_config:
                additional_kwargs.update(method_config)

        while True:
            result = self._sc.api_call(
                "{}.list".format(api_key),
                http_verb='GET',
                params=additional_kwargs
            )

            for r in result[result_key]:
                results[r['id']] = r

            cursor = result['response_metadata']['next_cursor']

            if cursor == '':
                break

            additional_kwargs['cursor'] = cursor

        self._results[resource] = results
        return results

    @classmethod
    def create_using_queries(cls, integration_name, init_usergroups=False):
        app_interface_settings = queries.get_app_interface_settings()
        slack_workspace = {'workspace': queries.get_slack_workspace()}
        return cls.create_from_dict(slack_workspace, app_interface_settings,
                                    integration_name, init_usergroups)

    @classmethod
    def create_from_dict(cls, slack_workspace, app_interface_settings,
                         integration_name, init_usergroups=False,
                         channel=None):

        if 'workspace' not in slack_workspace:
            raise ValueError(
                'Slack workspace not containing keyword "workspace"')
        workspace_name = slack_workspace['workspace']['name']
        client_config = slack_workspace['workspace'].get('api_client')

        [slack_integration_config] = \
            [i for i in slack_workspace['workspace']['integrations'] if
             i['name'] == integration_name]

        token = slack_integration_config['token']
        icon_emoji = slack_integration_config['icon_emoji']
        username = slack_integration_config['username']

        if channel is None:
            channel = slack_workspace.get('channel') or \
                      slack_integration_config['channel']

        if client_config:
            api_config = SlackApiConfig.from_dict(client_config)
        else:
            api_config = SlackApiConfig()

        api = cls(workspace_name, token,
                  secret_reader_settings=app_interface_settings,
                  init_usergroups=init_usergroups, channel=channel,
                  icon_emoji=icon_emoji, username=username,
                  api_config=api_config)

        return api
