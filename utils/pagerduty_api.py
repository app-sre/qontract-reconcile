import time
import pypd
import datetime

from slackclient import SlackClient

import utils.vault_client as vault_client


class PagerDutyApi(object):
    """Wrapper around PagerDuty API calls"""

    def __init__(self, token):
        token_path = token['path']
        token_field = token['field']
        pd_api_key = vault_client.read(token_path, token_field)
        pypd.api_key = pd_api_key

    def get_final_schedule(self, schedule_id):
        now = datetime.datetime.now().strftime("%Y-%m-%d")
        schedule = pypd.Schedule.fetch(
            id=schedule_id,
            since=now,
            until=now,
            time_zone='UTC')
        entries = schedule['final_schedule']['rendered_schedule_entries']
        if len(entries) != 1:
            return None
        [entry] = entries

        user_id = entry['user']['id']
        users = pypd.User.find()
        user = [u for u in users if u['id'] == user_id]
        [user] = user
        redhat_username = user['email'].replace('@redhat.com', '')
        print(redhat_username)
