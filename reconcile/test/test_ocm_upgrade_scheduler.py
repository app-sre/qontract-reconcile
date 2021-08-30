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
