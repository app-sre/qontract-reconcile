import os
import time
import logging
from typing import Dict

from slackclient import SlackClient
from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.config import get_config

# Default result sizes to return from APIs
CHANNELS_LIMIT = os.environ.get('SLACK_API_CHANNELS_LIMIT', 1000)
USERS_LIMIT = os.environ.get('SLACK_API_USERS_LIMIT', 1000)


class UserNotFoundException(Exception):
    pass


class UsergroupNotFoundException(Exception):
    pass


class SlackApi:
    """Wrapper around Slack API calls"""

    def __init__(self, workspace_name, token,
                 settings=None,
                 init_usergroups=True,
                 **chat_kwargs):
        self.workspace_name = workspace_name
        secret_reader = SecretReader(settings=settings)
        slack_token = secret_reader.read(token)
        self.sc = SlackClient(slack_token)
        self.results = {}
        self.chat_kwargs = chat_kwargs
        if init_usergroups:
            self._initiate_usergroups()

    def chat_post_message(self, text):
        self.sc.api_call(
            "chat.postMessage",
            text=text,
            **self.chat_kwargs
        )

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

    @retry()
    def _initiate_usergroups(self):
        result = self.sc.api_call(
            "usergroups.list",
            include_users=True
        )
        if not result['ok']:
            raise Exception(result['error'])
        self.usergroups = result['usergroups']

    def get_usergroup(self, handle):
        usergroup = [g for g in self.usergroups if g['handle'] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        [usergroup] = usergroup
        return usergroup

    @retry()
    def update_usergroup(self, id, channels_list, description):
        channels = ','.join(channels_list)
        self.sc.api_call(
            "usergroups.update",
            usergroup=id,
            channels=channels,
            description=description,
        )

    def update_usergroup_users(self, id, users_list):
        # since Slack API does not support empty usergroups
        # we can trick it by passing a deleted user
        if len(users_list) == 0:
            users_list = [self.get_random_deleted_user()]
        users = ','.join(users_list)
        self.sc.api_call(
            "usergroups.users.update",
            usergroup=id,
            users=users,
        )

    def get_random_deleted_user(self):
        for user_id, user_data in self._get('users', limit=USERS_LIMIT).items():
            if user_data['deleted'] is True:
                return user_id

        logging.error('could not find a deleted user, ' +
                      'empty usergroup will not work')
        return ''

    def get_user_id_by_name(self, user_name):
        config = get_config()
        mail_address = config['smtp']['mail_address']
        result = self.sc.api_call(
            "users.lookupByEmail",
            email=f"{user_name}@{mail_address}"
        )
        if not result['ok']:
            raise UserNotFoundException(result['error'])
        return result['user']['id']

    def get_channels_by_names(self, channels_names, limit=CHANNELS_LIMIT):
        return {k: v['name'] for k, v in self._get('channels',
                                                   limit=limit).items()
                if v['name'] in channels_names}

    def get_channels_by_ids(self, channels_ids, limit=CHANNELS_LIMIT):
        return {k: v['name'] for k, v in self._get('channels',
                                                   limit=limit).items()
                if k in channels_ids}

    def get_users_by_names(self, user_names, limit=USERS_LIMIT):
        return {k: v['name'] for k, v in self._get('users',
                                                   limit=limit).items()
                if v['name'] in user_names}

    def get_users_by_ids(self, users_ids, limit=USERS_LIMIT):
        return {k: v['name'] for k, v in self._get('users',
                                                   limit=limit).items()
                if k in users_ids}

    @retry()
    def _get(self, type: str, **kwargs) -> Dict:
        """
        Get Slack resources by type. This method uses a cache to ensure that
        each resource type is only fetched once.

        :param type: resource type
        :param **kwargs: other args to pass to the API call (ex. limit)
        :return: data from API call
        """
        result_key = 'members' if type == 'users' else type
        api_key = 'conversations' if type == 'channels' else type
        results = {}
        cursor = ''

        if type in self.results:
            return self.results[type]

        while True:
            result = self.sc.api_call(
                "{}.list".format(api_key),
                cursor=cursor,
                **kwargs
            )
            if 'error' in result and result['error'] == 'ratelimited':
                retry_after = result['headers']['retry-after']
                time.sleep(int(retry_after))
                continue
            for r in result[result_key]:
                results[r['id']] = r
            cursor = result['response_metadata']['next_cursor']
            if cursor == '':
                break

        self.results[type] = results
        return results
