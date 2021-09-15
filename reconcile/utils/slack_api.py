import logging
from typing import Sequence, Dict, Any, Mapping, Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import RateLimitErrorRetryHandler, RetryHandler, \
    RetryState, HttpRequest, HttpResponse

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.config import get_config

MAX_RETRIES = 5


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


class SlackApi:
    """Wrapper around Slack API calls"""

    def __init__(self,
                 workspace_name: str,
                 token: Mapping[str, str],
                 settings: Optional[Mapping[str, Any]] = None,
                 init_usergroups=True,
                 channel: Optional[str] = None,
                 **chat_kwargs) -> None:
        """
        :param workspace_name: Slack workspace name (ex. coreos)
        :param token: data to pass to SecretReader.read() to get the token
        :param settings: settings to pass to SecretReader
        :param init_usergroups: whether or not to get a list of all Slack
        usergroups when instantiated
        :param channel: the Slack channel to post messages to, only used
        when posting messages to a channel
        :param chat_kwargs: any other kwargs that can be used to post Slack
        channel messages
        """
        self.workspace_name = workspace_name

        secret_reader = SecretReader(settings=settings)
        slack_token = secret_reader.read(token)

        self._sc = WebClient(token=slack_token)
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
            max_retry_count=MAX_RETRIES)
        server_error_handler = ServerErrorRetryHandler(
            max_retry_count=MAX_RETRIES)

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

        self._sc.usergroups_users_update(usergroup=id, users=users_list)

    def get_random_deleted_user(self):
        for user_id, user_data in self._get('users').items():
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
        return {k: v['name'] for k, v in self._get('channels').items()
                if v['name'] in channels_names}

    def get_channels_by_ids(self, channels_ids):
        return {k: v['name'] for k, v in self._get('channels').items()
                if k in channels_ids}

    def get_users_by_names(self, user_names):
        return {k: v['name'] for k, v in self._get('users').items()
                if v['name'] in user_names}

    def get_users_by_ids(self, users_ids):
        return {k: v['name'] for k, v in self._get('users').items()
                if k in users_ids}

    @staticmethod
    def _get_api_results_limit(resource_type):
        # This will be replaced with getting the data from app-interface in
        # a future PR.
        api_limits = {
            'users': 1000,
            'channels': 1000
        }

        return api_limits.get(resource_type)

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
        additional_kwargs = {'cursor': ''}

        api_result_limit = self._get_api_results_limit(resource)

        if api_result_limit:
            additional_kwargs['limit'] = api_result_limit

        if resource in self._results:
            return self._results[resource]

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
