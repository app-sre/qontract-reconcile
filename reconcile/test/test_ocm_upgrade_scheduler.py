from unittest import TestCase
from unittest.mock import patch, Mock
from croniter import croniter
from datetime import datetime
from dateutil import parser
import pytest

import reconcile.ocm_upgrade_scheduler as ous


class TestUpdateHistory(TestCase):
    @patch.object(ous, "datetime", Mock(wraps=datetime))
    def test_update_history(self):
        history = {
            "check_in": "2021-08-29 18:00:00",
            "versions": {
                "version1": {
                    "workloads": {
                        "workload1": {
                            "soak_days": 21.0,
                            "reporting": ["cluster1", "cluster2"],
                        },
                        "workload2": {"soak_days": 6.0, "reporting": ["cluster3"]},
                    }
                }
            },
        }
        ous.datetime.utcnow.return_value = parser.parse("2021-08-30 18:00:00.00000")
        upgrade_policies = [
            {
                "workloads": ["workload1"],
                "cluster": "cluster1",
                "current_version": "version1",
            },
            {
                "workloads": ["workload1"],
                "cluster": "cluster2",
                "current_version": "version1",
            },
            {
                "workloads": ["workload2"],
                "cluster": "cluster3",
                "current_version": "version1",
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
                            "reporting": ["cluster1", "cluster2"],
                        },
                        "workload2": {"soak_days": 7.0, "reporting": ["cluster3"]},
                    }
                }
            },
        }
        self.assertEqual(expected, history)


class TestVersionConditionsMet(TestCase):
    def setUp(self):
        self.version = "1.2.3"
        self.ocm_name = "ocm"
        self.workload = "workload1"
        self.history = {
            self.ocm_name: {
                "versions": {
                    self.version: {"workloads": {self.workload: {"soak_days": 2.0}}}
                }
            }
        }

    def test_conditions_met_larger(self):
        upgrade_conditions = {"soakDays": 1.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_met_equal(self):
        upgrade_conditions = {"soakDays": 2.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_not_met(self):
        upgrade_conditions = {"soakDays": 3.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertFalse(conditions_met)

    def test_soak_zero_for_new_version(self):
        upgrade_conditions = {"soakDays": 0.0}

        conditions_met = ous.version_conditions_met(
            "0.0.0",
            self.history,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)


class TestUpgradeLock:
    @staticmethod
    @pytest.fixture
    @patch("reconcile.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm_map(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.get_available_upgrades.return_value = ["4.3.5", "4.3.6"]
        ocm.version_blocked.return_value = False
        return map

    @staticmethod
    def set_upgradeable():
        ous.version_conditions_met.return_value = True
        ous.datetime.utcnow.return_value = parser.parse("2021-08-30 18:00:00.00000")
        schedule = ous.croniter.return_value
        schedule.get_next.return_value = parser.parse("2021-08-30 19:00:00.00000")
        return True

    current_cluster1 = {
        "cluster": "cluster1",
    }

    desired_cluster1 = {
        "cluster": "cluster1",
        "current_version": "4.3.0",
        "channel": "stable",
        "schedule": None,
        "workloads": None,
        "conditions": {"mutexes": ["mutex1"]},
    }

    expected_cluster1 = {
        "action": "create",
        "cluster": "cluster1",
        "version": "4.3.6",
        "schedule_type": "manual",
        "next_run": "2021-08-30T19:00:00Z",
    }

    @patch.object(ous, "datetime", Mock(wraps=datetime))
    @patch.object(ous, "croniter", Mock(wraps=croniter))
    @patch.object(ous, "version_conditions_met", Mock())
    # cluster needing upgrade, and able to (not locked out)
    def test_calculate_diff_no_lock(self, ocm_map):
        current_state = []
        desired_state = [self.desired_cluster1]
        self.set_upgradeable()
        diffs = ous.calculate_diff(current_state, desired_state, ocm_map, {})
        expected = [self.expected_cluster1]
        assert diffs == expected

    @patch.object(ous, "datetime", Mock(wraps=datetime))
    @patch.object(ous, "croniter", Mock(wraps=croniter))
    @patch.object(ous, "version_conditions_met", Mock())
    # cluster needing upgrade, but mutex held by an other cluster
    def test_calculate_diff_locked_out(self, ocm_map):
        current_state = [self.current_cluster1]
        desired_cluster2 = self.desired_cluster1.copy()
        desired_cluster2["cluster"] = "cluster2"
        desired_state = [self.desired_cluster1, desired_cluster2]
        self.set_upgradeable()

        diffs = ous.calculate_diff(current_state, desired_state, ocm_map, {})

        expected = []
        assert diffs == expected

    @patch.object(ous, "datetime", Mock(wraps=datetime))
    @patch.object(ous, "croniter", Mock(wraps=croniter))
    @patch.object(ous, "version_conditions_met", Mock())
    # 2 clusters needing upgrade, but using the same mutex. Only the first one will get upgraded
    def test_calculate_diff_inter_lock(self, ocm_map):
        current_state = []
        desired_cluster2 = self.desired_cluster1.copy()
        desired_cluster2["cluster"] = "cluster2"
        desired_state = [self.desired_cluster1, desired_cluster2]
        self.set_upgradeable()

        diffs = ous.calculate_diff(current_state, desired_state, ocm_map, {})

        expected = [self.expected_cluster1]
        assert diffs == expected


class TestDesiredState(TestCase):
    @staticmethod
    def cluster(name, version, soakDays):
        return {
            "name": name,
            "spec": {
                "version": version,
                "channel": None,
            },
            "upgradePolicy": {
                "conditions": {
                    "soakDays": soakDays,
                },
            },
        }

    @staticmethod
    def policy(name, version, soakDays):
        return {
            "cluster": name,
            "current_version": version,
            "channel": None,
            "conditions": {
                "soakDays": soakDays,
            },
        }

    # cluster upgrades are prioritized according to their current versions
    def test_sorted_version(self):
        clusters = [
            self.cluster("cluster2", "4.2.0", 0),
            self.cluster("cluster1", "4.1.0", 0),
            self.cluster("cluster3", "4.3.0", 0),
        ]
        expected = [
            self.policy("cluster1", "4.1.0", 0),
            self.policy("cluster2", "4.2.0", 0),
            self.policy("cluster3", "4.3.0", 0),
        ]
        state = ous.fetch_desired_state(clusters)
        self.assertEqual(state, expected)

    # cluster upgrades are prioritized according to their soakdays
    def test_sorted_soakDays(self):
        clusters = [
            self.cluster("cluster2", "4.1.0", 2),
            self.cluster("cluster1", "4.1.0", 1),
            self.cluster("cluster3", "4.1.0", 3),
        ]
        expected = [
            self.policy("cluster1", "4.1.0", 1),
            self.policy("cluster2", "4.1.0", 2),
            self.policy("cluster3", "4.1.0", 3),
        ]
        state = ous.fetch_desired_state(clusters)
        self.assertEqual(state, expected)

    # cluster upgrades are prioritized according to their curent version and soakdays
    # in that order
    # The test TestUpgradeLock.test_calculate_diff_inter_lock above ensures that
    # only the first cluster with a given mutex will get upgraded.
    def test_sorted_version_soakDays(self):
        clusters = [
            self.cluster("cluster22", "4.2.0", 2),
            self.cluster("cluster12", "4.1.0", 2),
            self.cluster("cluster11", "4.1.0", 1),
            self.cluster("cluster21", "4.2.0", 1),
        ]
        expected = [
            self.policy("cluster11", "4.1.0", 1),
            self.policy("cluster12", "4.1.0", 2),
            self.policy("cluster21", "4.2.0", 1),
            self.policy("cluster22", "4.2.0", 2),
        ]
        state = ous.fetch_desired_state(clusters)
        self.assertEqual(state, expected)
