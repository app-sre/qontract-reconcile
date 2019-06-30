import pypd
import datetime
import requests

import utils.vault_client as vault_client


class PagerDutyApi(object):
    """Wrapper around PagerDuty API calls"""

    def __init__(self, token):
        token_path = token['path']
        token_field = token['field']
        pd_api_key = vault_client.read(token_path, token_field)
        pypd.api_key = pd_api_key

    def get_pagerduty_users(self, resource_type, resource_id):
        now = datetime.datetime.utcnow()

        try:
            if resource_type == 'schedule':
                users = self.get_schedule_users(resource_id, now)
            elif resource_type == 'escalationPolicy':
                users = self.get_escalation_policy_users(resource_id, now)
        except requests.exceptions.HTTPError:
            return None

        return users

    def get_schedule_users(self, schedule_id, now):
        s = pypd.Schedule.fetch(
            id=schedule_id,
            since=now,
            until=now,
            time_zone='UTC')
        entries = s['final_schedule']['rendered_schedule_entries']
        return [entry['user']['summary'] for entry in entries]

    def get_escalation_policy_users(self, escalation_policy_id, now):
        ep = pypd.EscalationPolicy.fetch(
            id=escalation_policy_id,
            since=now,
            until=now,
            time_zone='UTC')
        users = []
        rules = ep['escalation_rules']
        for rule in rules:
            targets = rule['targets']
            for target in targets:
                target_type = target['type']
                if target_type == 'schedule_reference':
                    schedule_users = \
                        self.get_schedule_users(target['id'], now)
                    users.extend(schedule_users)
                elif target_type == 'user_reference':
                    users.append(target['summary'])
            if users and rule['escalation_delay_in_minutes'] != 0:
                # process rules until users are found
                # and next escalation is not 0 minutes from now
                break
        return users
