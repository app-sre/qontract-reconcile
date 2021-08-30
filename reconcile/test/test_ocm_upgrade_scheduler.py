from unittest import TestCase
from unittest.mock import patch, Mock
from datetime import datetime
from dateutil import parser

import reconcile.ocm_upgrade_scheduler as ous


class TestUpdateHistory(TestCase):
    @patch.object(ous, 'datetime', Mock(wraps=datetime))
    def test_update_history(self):
        history = {
            "check_in": "2021-08-29 18:00:00",
            "versions": {
                "version1": {
                    "workloads": {
                        "workload1": {
                            "soak_days": 21.0,
                            "reporting": [
                                "cluster1",
                                "cluster2"
                            ]
                        },
                        "workload2": {
                            "soak_days": 6.0,
                            "reporting": [
                                "cluster3"
                            ]
                        }
                    }
                }
            }
        }
        ous.datetime.utcnow.return_value = \
            parser.parse("2021-08-30 18:00:00.00000")
        upgrade_policies = [
            {
                'workloads': ['workload1'],
                'cluster': 'cluster1',
                'current_version': 'version1'
            },
            {
                'workloads': ['workload1'],
                'cluster': 'cluster2',
                'current_version': 'version1'
            },
            {
                'workloads': ['workload2'],
                'cluster': 'cluster3',
                'current_version': 'version1'
            },
        ]
        ous.update_history(history, upgrade_policies)
        expected = {
            "check_in": "2021-08-30 18:00:00",
            "versions": {
                "version1": {
                    "workloads": {
                        "workload1": {
                            "soak_days": 23.0,
                            "reporting": [
                                "cluster1",
                                "cluster2"
                            ]
                        },
                        "workload2": {
                            "soak_days": 7.0,
                            "reporting": [
                                "cluster3"
                            ]
                        }
                    }
                }
            }
        }
        self.assertEqual(expected, history)


class TestVersionConditionsMet(TestCase):
    def setUp(self):
        self.version = '1.2.3'
        self.ocm_name = 'ocm'
        self.workload = 'workload1'
        self.history = {
            self.ocm_name: {
                'versions': {
                    self.version: {
                        'workloads': {
                            self.workload: {
                                'soak_days': 2.0
                            }
                        }
                    }
                }
            }
        }

    def test_conditions_met(self):
        upgrade_conditions = {
            'soakDays': 1.0
        }

        conditions_met = ous.version_conditions_met(
            self.version,
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_not_met(self):
        upgrade_conditions = {
            'soakDays': 3.0
        }

        conditions_met = ous.version_conditions_met(
            self.version,
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertFalse(conditions_met)

    def test_soak_zero_for_new_version(self):
        upgrade_conditions = {
            'soakDays': 0.0
        }

        conditions_met = ous.version_conditions_met(
            '0.0.0',
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)
