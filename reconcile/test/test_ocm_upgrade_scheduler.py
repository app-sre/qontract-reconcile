from datetime import datetime
from typing import Any
from unittest import TestCase
from unittest.mock import (
    Mock,
    patch,
)

import pytest
from croniter import croniter
from dateutil import parser

import reconcile.ocm_upgrade_scheduler as ous
from reconcile.utils.cluster_version_data import VersionData
from reconcile.utils.ocm import Sector


class TestUpdateHistory(TestCase):
    @patch.object(ous, "datetime", Mock(wraps=datetime))
    def test_update_history(self):
        history = {
            "check_in": "2021-08-29T18:00:00",
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
        ous.datetime.utcnow.return_value = parser.parse("2021-08-30T18:00:00.00000")
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
        version_data = VersionData(**history)
        ous.update_history(version_data, upgrade_policies)
        expected = {
            "check_in": "2021-08-30T18:00:00",
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
        self.assertEqual(expected, version_data.jsondict())


class TestVersionConditionsMetSoakDays(TestCase):
    def setUp(self):
        self.version = "1.2.3"
        self.ocm_name = "ocm"
        self.workload = "workload1"
        version_data_dict = {
            "check_in": None,
            "versions": {
                self.version: {
                    "workloads": {
                        self.workload: {
                            "soak_days": 2.0,
                            "reporting": ["cluster1", "cluster2"],
                        }
                    }
                }
            },
        }
        version_data = VersionData(**version_data_dict)
        self.version_data_map = {self.ocm_name: version_data}

    def test_conditions_met_larger(self):
        upgrade_conditions = {"soakDays": 1.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_met_equal(self):
        upgrade_conditions = {"soakDays": 2.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_not_met(self):
        upgrade_conditions = {"soakDays": 3.0}

        conditions_met = ous.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertFalse(conditions_met)

    def test_soak_zero_for_new_version(self):
        upgrade_conditions = {"soakDays": 0.0}

        conditions_met = ous.version_conditions_met(
            "0.0.0",
            self.version_data_map,
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
        ous.datetime.utcnow.return_value = parser.parse("2021-08-30T18:00:00.00000")
        schedule = ous.croniter.return_value
        schedule.get_next.return_value = parser.parse("2021-08-30T19:00:00.00000")
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
        "gates_to_agree": [],
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


class TestUpgradeableVersion:
    @staticmethod
    @pytest.fixture
    @patch("reconcile.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.get_available_upgrades.return_value = ["4.3.5", "4.3.6", "4.4.1"]
        ocm.version_blocked.return_value = False
        return map.get("foo")

    @staticmethod
    @pytest.fixture
    def ocm_gated(ocm):
        ocm.get_version_gates.side_effect = (
            lambda v: [{"id": 1, "version_raw_prefix": 4.4}] if v == "4.4" else []
        )
        return ocm

    @staticmethod
    @pytest.fixture
    def upgrade_policy() -> dict[str, Any]:
        return {
            "current_version": "4.3.5",
            "channel": "stable",
            "workloads": "test",
            "conditions": {
                "soakdays": 1,
            },
        }

    @staticmethod
    def test_upgradeable_version_blocked(upgrade_policy, ocm):
        ocm.version_blocked.return_value = True
        x = ous.upgradeable_version(upgrade_policy, {}, ocm)
        assert x is None

    @staticmethod
    def test_upgradeable_version_no_gate(upgrade_policy, ocm):
        x = ous.upgradeable_version(upgrade_policy, {}, ocm)
        assert x == "4.4.1"

    @staticmethod
    def test_upgradeable_version_requires_agreement(upgrade_policy, ocm_gated):
        x = ous.upgradeable_version(upgrade_policy, {}, ocm_gated)
        assert x == "4.4.1"


class TestVersionGateAgreement:
    @staticmethod
    @pytest.fixture
    @patch("reconcile.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.get_version_gates.return_value = [{"id": 1}]
        ocm.get_version_agreement.return_value = [{"version_gate": {"id": 2}}]
        return map.get("foo")

    @staticmethod
    def test_gates_to_agree_basic(ocm):
        gta = ous.gates_to_agree("4.9", "foo", ocm)
        assert len(gta) == 1
        assert gta[0] == 1

    @staticmethod
    def test_gates_to_agree_empty(ocm):
        ocm.get_version_agreement.return_value.append({"version_gate": {"id": 1}})
        gta = ous.gates_to_agree("4.9", "foo", ocm)
        assert len(gta) == 0


class TestUpgradePriority(TestCase):
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
        actual = [
            self.policy("cluster2", "4.2.0", 0),
            self.policy("cluster1", "4.1.0", 0),
            self.policy("cluster3", "4.3.0", 0),
        ]
        expected = [
            self.policy("cluster1", "4.1.0", 0),
            self.policy("cluster2", "4.2.0", 0),
            self.policy("cluster3", "4.3.0", 0),
        ]
        state = sorted(actual, key=ous.sort_key)
        self.assertEqual(state, expected)

    # cluster upgrades are prioritized according to their soakdays
    def test_sorted_soakDays(self):
        actual = [
            self.policy("cluster2", "4.1.0", 2),
            self.policy("cluster1", "4.1.0", 1),
            self.policy("cluster3", "4.1.0", 3),
        ]
        expected = [
            self.policy("cluster1", "4.1.0", 1),
            self.policy("cluster2", "4.1.0", 2),
            self.policy("cluster3", "4.1.0", 3),
        ]
        state = sorted(actual, key=ous.sort_key)
        self.assertEqual(state, expected)

    # cluster upgrades are prioritized according to their curent version and soakdays
    # in that order
    # The test TestUpgradeLock.test_calculate_diff_inter_lock above ensures that
    # only the first cluster with a given mutex will get upgraded.
    def test_sorted_version_soakDays(self):
        actual = [
            self.policy("cluster22", "4.2.0", 2),
            self.policy("cluster12", "4.1.0", 2),
            self.policy("cluster11", "4.1.0", 1),
            self.policy("cluster21", "4.2.0", 1),
        ]
        expected = [
            self.policy("cluster11", "4.1.0", 1),
            self.policy("cluster12", "4.1.0", 2),
            self.policy("cluster21", "4.2.0", 1),
            self.policy("cluster22", "4.2.0", 2),
        ]
        state = sorted(actual, key=ous.sort_key)
        self.assertEqual(state, expected)


class TestVersionConditionsMetSector:
    class OCMSpec:
        class OCMSpecSpec:
            version: str

        spec: OCMSpecSpec

        def __init__(self) -> None:
            self.spec = self.OCMSpecSpec()
            self.spec.version = "0.0.0"

    def ocmspec(self, version):
        s = self.OCMSpec()
        s.spec.version = version
        return s

    @pytest.fixture
    def ocm1(self, mocker):
        o = mocker.patch("reconcile.ocm_upgrade_scheduler.OCM", autospec=True)
        o.name = "ocm1"
        return o

    @pytest.fixture
    def sector1_ocm1(self, ocm1):
        return Sector(name="sector1", ocm=ocm1)

    @staticmethod
    @pytest.fixture
    def sector2_ocm1(ocm1, sector1_ocm1):
        return Sector(name="sector2", ocm=ocm1, dependencies=[sector1_ocm1])

    @staticmethod
    @pytest.fixture
    def sector3_ocm1(ocm1, sector2_ocm1):
        return Sector(name="sector3", ocm=ocm1, dependencies=[sector2_ocm1])

    @pytest.fixture
    def cluster_high_version(self):
        return {
            "name": "high-version-sector1-ocm1",
            "upgradePolicy": {"workloads": ["workload1"]},
            "ocmspec": self.ocmspec("2.0.0"),
        }

    @pytest.fixture
    def cluster_low_version(self):
        return {
            "name": "low-version-sector1-ocm1",
            "upgradePolicy": {"workloads": ["workload1"]},
            "ocmspec": self.ocmspec("1.0.0"),
        }

    def test_conditions_met_no_deps(self, sector1_ocm1: Sector):
        upgrade_conditions = {"sector": sector1_ocm1}
        assert ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_no_cluster(self, sector2_ocm1: Sector):
        upgrade_conditions = {"sector": sector2_ocm1}
        assert ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

    # return the ocmspec of the cluster from its name
    def side_effect_ocmspec(self, clusters: list[dict]):
        map = {c["name"]: c["ocmspec"] for c in clusters}
        return map.get

    def set_clusters(self, mocker, sector: Sector, clusters: list[dict]):
        sector.cluster_infos = clusters
        mocker.patch.object(
            sector,
            "ocmspec",
            side_effect=self.side_effect_ocmspec(clusters),
        )

    def test_conditions_met_single_deps_high_version(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector2_ocm1: Sector,
        cluster_high_version,
    ):
        upgrade_conditions = {"sector": sector2_ocm1}
        self.set_clusters(mocker, sector1_ocm1, [cluster_high_version])
        assert ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_low_version(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector2_ocm1: Sector,
        cluster_low_version,
    ):
        upgrade_conditions = {"sector": sector2_ocm1}
        self.set_clusters(mocker, sector1_ocm1, [cluster_low_version])
        assert not ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_mix_versions(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector2_ocm1: Sector,
        cluster_low_version,
        cluster_high_version,
    ):
        upgrade_conditions = {"sector": sector2_ocm1}
        self.set_clusters(
            mocker, sector1_ocm1, [cluster_low_version, cluster_high_version]
        )
        assert not ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

    # first dependency level (sector2) contains no cluster with the workload,
    # so we're recursing dependencies down to sector1
    # sector3 -> sector2 -> sector1
    def test_conditions_met_deep_deps_mix_versions(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector3_ocm1: Sector,
        cluster_low_version,
        cluster_high_version,
    ):
        upgrade_conditions = {"sector": sector3_ocm1}

        # no clusters in deps: upgrade ok
        assert ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

        # all clusters with higher version in deps: upgrade ok
        self.set_clusters(mocker, sector1_ocm1, [cluster_high_version])
        assert ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

        # no cluster with higher version in deps: upgrade not ok
        self.set_clusters(mocker, sector1_ocm1, [cluster_low_version])
        assert not ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )

        # not all clusters with higher version in deps: upgrade not ok
        self.set_clusters(
            mocker, sector1_ocm1, [cluster_low_version, cluster_high_version]
        )
        assert not ous.version_conditions_met(
            "1.2.3", {}, "ocm1", ["workload1"], upgrade_conditions
        )


class TestAct:
    @staticmethod
    @pytest.fixture
    def ocm_map(mocker):
        mock_ocm_map = mocker.patch(
            "reconcile.ocm_upgrade_scheduler.OCMMap", autospec=True
        )
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        map.instances.return_value = {"testing": ocm}.keys()
        ocm.get_available_upgrades.return_value = ["4.9.5", "4.10.1"]
        ocm.version_blocked.return_value = False
        return map

    @staticmethod
    @pytest.fixture
    def diff_gated_version():
        return [
            {
                "action": "create",
                "cluster": "test1",
                "version": "1.2.3",
                "schedule_type": "manual",
                "next_run": datetime.now(),
                "gates_to_agree": ["uuid-1"],
            }
        ]

    @staticmethod
    @pytest.fixture
    def diff_with_delete(diff_gated_version):
        diff_gated_version.append(
            {
                "action": "delete",
                "cluster": "test2",
                "version": "1.2.3",
            }
        )
        return diff_gated_version

    @staticmethod
    def test_act_gated_version(ocm_map, diff_gated_version):
        ous.act(False, diff_gated_version, ocm_map)
        ocm_map.get("test1").create_version_agreement.assert_called_once_with(
            "uuid-1", "test1"
        )
        ocm_map.get("test1").create_upgrade_policy.assert_called_once_with(
            "test1", diff_gated_version[0]
        )

    @staticmethod
    def test_act_with_delete(ocm_map, diff_with_delete):
        ous.act(False, diff_with_delete, ocm_map)
        ocm_map.get("test1").create_upgrade_policy.assert_called_once_with(
            "test1", diff_with_delete[1]
        )
        ocm_map.get("test2").delete_upgrade_policy("test2", diff_with_delete[0])
