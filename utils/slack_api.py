import time

from slackclient import SlackClient

import utils.vault_client as vault_client


class UsergroupNotFoundException(Exception):
    pass


class SlackApi(object):
    """Wrapper around Slack API calls"""

    def __init__(self, token):
        token_path = token['path']
        token_field = token['field']
        token = vault_client.read(token_path, token_field)
        self.sc = SlackClient(token)
        self.results = {}

    def describe_usergroup(self, handle):
        usergroup = self.get_usergroup(handle)
        usergroup_id = usergroup['id']

        users_ids = self.get_usergroup_users(usergroup_id)
        users = self.get_users_by_ids(users_ids)

        channels_ids = usergroup['prefs']['channels']
        channels = self.get_channels_by_ids(channels_ids)

        return users, channels

    def get_usergroup_id(self, handle):
        usergroup = self.get_usergroup(handle)
        return usergroup['id']

    def get_usergroup(self, handle):
        result = self.sc.api_call(
            "usergroups.list",
        )
        usergroup = [g for g in result['usergroups'] if g['handle'] == handle]
        if len(usergroup) != 1:
            raise UsergroupNotFoundException(handle)
        [usergroup] = usergroup
        return usergroup

    def update_usergroup_channels(self, id, channels):
        self.sc.api_call(
            "usergroups.update",
            usergroup=id,
            channels=channels,
        )

    def get_usergroup_users(self, id):
        self.sc.api_call(
            "usergroups.users.list",
            usergroup=id,
        )

    def update_usergroup_users(self, id, users):
        result = self.sc.api_call(
            "usergroups.users.update",
            usergroup=id,
            users=users,
        )
        return result

    def get_channels_by_names(self, channels_names):
        return {k: v for k, v in self.get('channels').items()
                if v in channels_names}

    def get_channels_by_ids(self, channels_ids):
        return {k: v for k, v in self.get('channels').items()
                if k in channels_ids}

    def get_users_by_names(self, users_names):
        return {k: v for k, v in self.get('users').items()
                if v in users_names}

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
