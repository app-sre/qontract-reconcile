import datetime

import requests
import pypd

from reconcile.utils.secret_reader import SecretReader


class PagerDutyUserNotFoundException(Exception):
    pass


class PagerDutyApi:
    """Wrapper around PagerDuty API calls"""

    def __init__(self, token, settings=None):
        secret_reader = SecretReader(settings=settings)
        pd_api_key = secret_reader.read(token)
        pypd.api_key = pd_api_key
        self.init_users()

    def init_users(self):
        self.users = pypd.User.find()

    def get_pagerduty_users(self, resource_type, resource_id):
        now = datetime.datetime.utcnow()

        try:
            if resource_type == "schedule":
                users = self.get_schedule_users(resource_id, now)
            elif resource_type == "escalationPolicy":
                users = self.get_escalation_policy_users(resource_id, now)
        except requests.exceptions.HTTPError:
            return None

        return users

    def get_user(self, user_id):
        for user in self.users:
            if user.id == user_id:
                return user.email.split("@")[0]

        # should never be reached as user_id comes from PagerDuty API itself
        raise PagerDutyUserNotFoundException(user_id)

    def get_schedule_users(self, schedule_id, now):
        s = pypd.Schedule.fetch(id=schedule_id, since=now, until=now, time_zone="UTC")
        entries = s["final_schedule"]["rendered_schedule_entries"]

        return [
            self.get_user(entry["user"]["id"])
            for entry in entries
            if not entry["user"].get("deleted_at")
        ]

    def get_escalation_policy_users(self, escalation_policy_id, now):
        ep = pypd.EscalationPolicy.fetch(
            id=escalation_policy_id, since=now, until=now, time_zone="UTC"
        )
        users = []
        rules = ep["escalation_rules"]
        for rule in rules:
            targets = rule["targets"]
            for target in targets:
                target_type = target["type"]
                if target_type == "schedule_reference":
                    schedule_users = self.get_schedule_users(target["id"], now)
                    users.extend(schedule_users)
                elif target_type == "user_reference":
                    users.append(self.get_user(target["id"]))
            if users and rule["escalation_delay_in_minutes"] != 0:
                # process rules until users are found
                # and next escalation is not 0 minutes from now
                break
        return users


class PagerDutyMap:
    """A collection of PagerDutyApi instances per PagerDuty instance"""

    def __init__(self, instances, settings=None):
        self.pd_apis = {}
        for i in instances:
            name = i["name"]
            token = i["token"]
            pd_api = PagerDutyApi(token, settings=settings)
            self.pd_apis[name] = pd_api

    def get(self, name):
        """Get PagerDutyApi by instance name

        Args:
            name (string): instance name

        Returns:
            PagerDutyApi: PagerDutyApi instance
        """
        return self.pd_apis.get(name)
