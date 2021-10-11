from datetime import datetime, timedelta

from unittest import TestCase
import reconcile.slack_usergroups as integ


class TestSupportFunctions(TestCase):
    def test_get_slack_usernames_from_schedule_none(self):
        result = integ.get_slack_usernames_from_schedule(None)
        self.assertEqual(result, [])

    def test_get_slack_usernames_from_schedule(self):
        now = datetime.utcnow()
        schedule = {
            'schedule': [
                {
                    'start': (now - timedelta(hours=1)).
                        strftime(integ.DATE_FORMAT),
                    'end': (now + timedelta(hours=1)).
                        strftime(integ.DATE_FORMAT),
                    'users': [
                        {
                            'org_username': 'user',
                            'slack_username': 'user'
                        }
                    ]
                }
            ]
        }
        result = integ.get_slack_usernames_from_schedule(schedule)
        self.assertEqual(result, ['user'])

    def test_get_slack_username_org_username(self):
        user = {
            'org_username': 'org',
            'slack_username': None,
        }
        result = integ.get_slack_username(user)
        self.assertEqual(result, 'org')

    def test_get_slack_username_slack_username(self):
        user = {
            'org_username': 'org',
            'slack_username': 'slack',
        }
        result = integ.get_slack_username(user)
        self.assertEqual(result, 'slack')

    def test_get_pagerduty_username_org_username(self):
        user = {
            'org_username': 'org',
            'pagerduty_username': None,
        }
        result = integ.get_pagerduty_name(user)
        self.assertEqual(result, 'org')

    def test_get_pagerduty_username_slack_username(self):
        user = {
            'org_username': 'org',
            'pagerduty_username': 'pd',
        }
        result = integ.get_pagerduty_name(user)
        self.assertEqual(result, 'pd')
