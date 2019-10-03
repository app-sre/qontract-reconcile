import time

from slackclient import SlackClient

import utils.vault_client as vault_client
from utils.retry import retry


class UsergroupNotFoundException(Exception):
    pass


class SlackApi(object):
    """Wrapper around Slack API calls"""

    def __init__(self, token):
        slack_token = vault_client.read(token)
        self.sc = SlackClient(slack_token)
        self.results = {}

    def chat_post_message(self, text, channel, icon_emoji, username):
        self.sc.api_call(
            "chat.postMessage",
            text=text,
            channel=channel,
            icon_emoji=icon_emoji,
            username=username
        )

    def describe_usergroup(self, handle):
        usergroup = self.get_usergroup(handle)
        usergroup_id = usergroup['id']
        description = usergroup['description']

        users_ids = self.get_usergroup_users(usergroup_id)
        users = self.get_users_by_ids(users_ids)

        channels_ids = usergroup['prefs']['channels']
        channels = self.get_channels_by_ids(channels_ids)

        return users, channels, description

    def get_usergroup_id(self, handle):
        usergroup = self.get_usergroup(handle)
        return usergroup['id']

    @retry()
    def get_usergroup(self, handle):
        result = self.sc.api_call(
            "usergroups.list",
        )
        if not result['ok']:
            raise Exception(result['error'])
        usergroup = [g for g in result['usergroups'] if g['handle'] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        [usergroup] = usergroup
        return usergroup

    def update_usergroup(self, id, channels_list, description):
        channels = ','.join(channels_list)
        self.sc.api_call(
            "usergroups.update",
            usergroup=id,
            channels=channels,
            description=description,
        )

    def get_usergroup_users(self, id):
        result = self.sc.api_call(
            "usergroups.users.list",
            usergroup=id,
        )
        return result['users']

    def update_usergroup_users(self, id, users_list):
        users = ','.join(users_list)
        self.sc.api_call(
            "usergroups.users.update",
            usergroup=id,
            users=users,
        )

    def get_channels_by_names(self, channels_names):
        return {k: v for k, v in self.get('channels').items()
                if v in channels_names}

    def get_channels_by_ids(self, channels_ids):
        return {k: v for k, v in self.get('channels').items()
                if k in channels_ids}

    def get_users_by_names(self, user_names):
        return {k: v for k, v in self.get('users').items()
                if v in user_names}

    def get_users_by_ids(self, users_ids):
        return {k: v for k, v in self.get('users').items()
                if k in users_ids}

    def get(self, type):
        result_key = 'members' if type == 'users' else type
        results = {}
        cursor = ''

        if type in self.results:
            return self.results[type]

        while True:
            result = self.sc.api_call(
                "{}.list".format(type),
                cursor=cursor
            )
            if 'error' in result and result['error'] == 'ratelimited':
                time.sleep(1)
                continue
            for r in result[result_key]:
                results[r['id']] = r['name']
            cursor = result['response_metadata']['next_cursor']
            if cursor == '':
                break

        self.results[type] = results
        return results
