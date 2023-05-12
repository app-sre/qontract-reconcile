from datetime import (
    datetime,
    timedelta,
)
from typing import Any
from unittest import TestCase
from unittest.mock import (
    Mock,
    patch,
)

import pytest
from croniter import croniter
from dateutil import parser

import reconcile.aus.base as aus
from reconcile.aus.models import (
    ConfiguredAddonUpgradePolicy,
    ConfiguredClusterUpgradePolicy,
    ConfiguredUpgradePolicy,
    ConfiguredUpgradePolicyConditions,
)
from reconcile.utils.cluster_version_data import (
    Stats,
    VersionData,
)
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
    Sector,
)


class TestUpdateHistory(TestCase):
    @patch.object(aus, "datetime", Mock(wraps=datetime))
    def test_update_history(self):
        history = {
            "check_in": "2021-08-29T18:00:00",
            "versions": {
                "4.12.1": {
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
        aus.datetime.utcnow.return_value = parser.parse("2021-08-30T18:00:00.00000")
        upgrade_policies = [
            aus.ConfiguredUpgradePolicy(
                **{
                    "workloads": ["workload1"],
                    "cluster": "cluster1",
                    "current_version": "4.12.1",
                    "conditions": {},
                    "schedule": "0 0 * * *",
                }
            ),
            aus.ConfiguredUpgradePolicy(
                **{
                    "workloads": ["workload1"],
                    "cluster": "cluster2",
                    "current_version": "4.12.1",
                    "conditions": {},
                    "schedule": "0 0 * * *",
                }
            ),
            aus.ConfiguredUpgradePolicy(
                **{
                    "workloads": ["workload2"],
                    "cluster": "cluster3",
                    "current_version": "4.12.1",
                    "conditions": {},
                    "schedule": "0 0 * * *",
                }
            ),
        ]
        version_data = VersionData(**history)
        aus.update_history(version_data, upgrade_policies)
        expected = {
            "check_in": "2021-08-30T18:00:00",
            "versions": {
                "4.12.1": {
                    "workloads": {
                        "workload1": {
                            "soak_days": 23.0,
                            "reporting": ["cluster1", "cluster2"],
                        },
                        "workload2": {"soak_days": 7.0, "reporting": ["cluster3"]},
                    }
                }
            },
            "stats": {
                "min_version": "4.12.1",
                "min_version_per_workload": {
                    "workload1": "4.12.1",
                    "workload2": "4.12.1",
                },
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
        upgrade_conditions = ConfiguredUpgradePolicyConditions(**{"soakDays": 1.0})

        conditions_met = aus.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_met_equal(self):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(**{"soakDays": 2.0})

        conditions_met = aus.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertTrue(conditions_met)

    def test_conditions_not_met(self):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(**{"soakDays": 3.0})

        conditions_met = aus.version_conditions_met(
            self.version,
            self.version_data_map,
            self.ocm_name,
            [self.workload],
            upgrade_conditions,
        )
        self.assertFalse(conditions_met)

    def test_soak_zero_for_new_version(self):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(**{"soakDays": 0.0})

        conditions_met = aus.version_conditions_met(
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
    @patch("reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm_map(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.get_available_upgrades.return_value = ["4.3.5", "4.3.6"]
        ocm.version_blocked.return_value = False
        return map

    @staticmethod
    def set_upgradeable():
        aus.version_conditions_met.return_value = True
        aus.datetime.utcnow.return_value = parser.parse("2021-08-30T18:00:00.00000")
        schedule = aus.croniter.return_value
        schedule.get_next.return_value = parser.parse("2021-08-30T19:00:00.00000")
        return True

    current_cluster1 = aus.ClusterUpgradePolicy(
        **{
            "cluster": "cluster1",
            "schedule_type": "manual",
            "version": "4.3.5",
        }
    )

    desired_cluster1 = ConfiguredClusterUpgradePolicy(
        **{
            "cluster": "cluster1",
            "current_version": "4.3.0",
            "channel": "stable",
            "schedule": "* * * * *",
            "workloads": [],
            "conditions": {"mutexes": ["mutex1"]},
        }
    )

    expected_policy_handler = aus.UpgradePolicyHandler(
        action="create",
        policy=aus.ClusterUpgradePolicy(
            **{
                "cluster": "cluster1",
                "version": "4.3.6",
                "schedule_type": "manual",
                "gates_to_agree": [],
                "next_run": "2021-08-30T19:00:00Z",
            }
        ),
    )

    @patch.object(aus, "datetime", Mock(wraps=datetime))
    @patch.object(aus, "croniter", Mock(wraps=croniter))
    @patch.object(aus, "version_conditions_met", Mock())
    # cluster needing upgrade, and able to (not locked out)
    def test_calculate_diff_no_lock(self, ocm_map):
        current_state = []
        desired_state = [self.desired_cluster1]
        self.set_upgradeable()
        diffs = aus.calculate_diff(current_state, desired_state, ocm_map, {})
        expected = [self.expected_policy_handler]
        assert diffs == expected

    @patch.object(aus, "datetime", Mock(wraps=datetime))
    @patch.object(aus, "croniter", Mock(wraps=croniter))
    @patch.object(aus, "version_conditions_met", Mock())
    # cluster needing upgrade, but mutex held by an other cluster
    def test_calculate_diff_locked_out(self, ocm_map):
        current_state = [self.current_cluster1]
        desired_cluster2 = self.desired_cluster1.copy()
        desired_cluster2.cluster = "cluster2"
        desired_state = [self.desired_cluster1, desired_cluster2]
        self.set_upgradeable()

        diffs = aus.calculate_diff(current_state, desired_state, ocm_map, {})

        expected = []
        assert diffs == expected

    @patch.object(aus, "datetime", Mock(wraps=datetime))
    @patch.object(aus, "croniter", Mock(wraps=croniter))
    @patch.object(aus, "version_conditions_met", Mock())
    # 2 clusters needing upgrade, but using the same mutex. Only the first one will get upgraded
    def test_calculate_diff_inter_lock(self, ocm_map):
        current_state = []
        desired_cluster2 = self.desired_cluster1.copy()
        desired_cluster2.cluster = "cluster2"
        desired_state = [self.desired_cluster1, desired_cluster2]
        self.set_upgradeable()

        diffs = aus.calculate_diff(current_state, desired_state, ocm_map, {})

        expected = [self.expected_policy_handler]
        assert diffs == expected


class TestUpgradeableVersion:
    @staticmethod
    @pytest.fixture
    @patch("reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.name = "foo"
        ocm.get_available_upgrades.return_value = ["4.3.5", "4.3.6", "4.4.1"]
        ocm.version_blocked.return_value = False
        return map.get("foo")

    @staticmethod
    @pytest.fixture
    def upgrade_policy() -> ConfiguredUpgradePolicy:
        return ConfiguredUpgradePolicy(
            **{
                "current_version": "4.3.5",
                "channel": "stable",
                "cluster": "test",
                "schedule": "manual",
                "workloads": ["workload1"],
                "conditions": ConfiguredUpgradePolicyConditions(soakDays=1),
            }
        )

    @staticmethod
    @pytest.fixture
    def version_data_map():
        return {
            "foo": VersionData(
                **{
                    "check_in": "2021-08-29T18:00:00",
                    "versions": {
                        "4.4.1": {
                            "workloads": {
                                "workload1": {
                                    "soak_days": 1.0,
                                    "reporting": ["cluster1", "cluster2"],
                                },
                            }
                        }
                    },
                }
            )
        }

    @staticmethod
    def test_upgradeable_version_blocked(upgrade_policy, ocm):
        upgrades = ocm.get_available_upgrades()
        ocm.version_blocked.return_value = True
        x = aus.upgradeable_version(upgrade_policy, {}, ocm, upgrades)
        assert x is None

    @staticmethod
    def test_upgradeable_version_no_gate(upgrade_policy, ocm, version_data_map):
        upgrades = ocm.get_available_upgrades()
        x = aus.upgradeable_version(upgrade_policy, version_data_map, ocm, upgrades)
        assert x == "4.4.1"


class TestVersionGateAgreement:
    @staticmethod
    @pytest.fixture
    @patch("reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True)
    def ocm(mock_ocm_map):
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.get_version_gates.return_value = [{"id": 1}]
        ocm.get_version_agreement.return_value = [{"version_gate": {"id": 2}}]
        return map.get("foo")

    @staticmethod
    def test_gates_to_agree_basic(ocm):
        gta = aus.gates_to_agree("4.8", "foo", "4.7.1", ocm)
        assert len(gta) == 1
        assert gta[0] == 1

    @staticmethod
    def test_gates_to_agree_empty(ocm):
        ocm.get_version_agreement.return_value.append({"version_gate": {"id": 1}})
        gta = aus.gates_to_agree("4.9", "foo", "4.8.1", ocm)
        assert len(gta) == 0

    @staticmethod
    def test_gates_to_agree_same_version(ocm):
        ocm.get_version_agreement.return_value.append({"version_gate": {"id": 1}})
        gta = aus.gates_to_agree("4.9", "foo", "4.9.1", ocm)
        assert len(gta) == 0


class TestUpgradePriority(TestCase):
    @staticmethod
    def policy(name: str, version: str, soakDays: int) -> ConfiguredUpgradePolicy:
        return ConfiguredUpgradePolicy(
            **{
                "cluster": name,
                "current_version": version,
                "schedule": "",
                "workloads": [],
                "conditions": ConfiguredUpgradePolicyConditions(
                    **{
                        "soakDays": soakDays,
                    }
                ),
            }
        )

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
        state = sorted(actual, key=aus.sort_key)
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
        state = sorted(actual, key=aus.sort_key)
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
        state = sorted(actual, key=aus.sort_key)
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
        o = mocker.patch("reconcile.aus.base.OCM", autospec=True)
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
    def cluster_high_version(self) -> dict[str, Any]:
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

    @pytest.fixture
    def empty_version_data_map(self):
        return {
            "ocm1": VersionData(
                check_in="2021-08-29T18:00:00",
                versions={},
                stats=Stats(min_version="1.0.0", min_version_per_workload={}),
            )
        }

    def test_conditions_met_no_deps(
        self, sector1_ocm1: Sector, empty_version_data_map: dict[str, VersionData]
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector1_ocm1)
        assert aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_no_cluster(
        self, sector2_ocm1: Sector, empty_version_data_map: dict[str, VersionData]
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector2_ocm1)
        assert aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
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
        cluster_high_version: dict[str, Any],
        empty_version_data_map: dict[str, VersionData],
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector2_ocm1)
        self.set_clusters(mocker, sector1_ocm1, [cluster_high_version])
        assert aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_low_version(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector2_ocm1: Sector,
        cluster_low_version: dict[str, Any],
        empty_version_data_map: dict[str, VersionData],
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector2_ocm1)
        self.set_clusters(mocker, sector1_ocm1, [cluster_low_version])
        assert not aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

    def test_conditions_met_single_deps_mix_versions(
        self,
        mocker,
        sector1_ocm1: Sector,
        sector2_ocm1: Sector,
        cluster_low_version,
        cluster_high_version: dict[str, Any],
        empty_version_data_map: dict[str, VersionData],
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector2_ocm1)
        self.set_clusters(
            mocker, sector1_ocm1, [cluster_low_version, cluster_high_version]
        )
        assert not aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
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
        cluster_high_version: dict[str, Any],
        empty_version_data_map: dict[str, VersionData],
    ):
        upgrade_conditions = ConfiguredUpgradePolicyConditions(sector=sector3_ocm1)

        # no clusters in deps: upgrade ok
        assert aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

        # all clusters with higher version in deps: upgrade ok
        self.set_clusters(mocker, sector1_ocm1, [cluster_high_version])
        assert aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

        # no cluster with higher version in deps: upgrade not ok
        self.set_clusters(mocker, sector1_ocm1, [cluster_low_version])
        assert not aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )

        # not all clusters with higher version in deps: upgrade not ok
        self.set_clusters(
            mocker, sector1_ocm1, [cluster_low_version, cluster_high_version]
        )
        assert not aus.version_conditions_met(
            "1.2.3", empty_version_data_map, "ocm1", ["workload1"], upgrade_conditions
        )


class TestAct:
    @staticmethod
    @pytest.fixture
    def ocm_map(mocker):
        mock_ocm_map = mocker.patch(
            "reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True
        )
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        map.instances.return_value = {"testing": ocm}.keys()
        ocm.get_available_upgrades.return_value = ["4.9.5", "4.10.1"]
        ocm.version_blocked.return_value = False
        return map

    class TestPolicy(aus.AbstractUpgradePolicy):
        created = False
        deleted = False

        def create(self, ocm: OCM):
            self.created = True

        def delete(self, ocm: OCM):
            self.deleted = True

        def summarize(self, ocm_org_name: str) -> str:
            return "do-something"

    @staticmethod
    def create_policy_with_action(action: str):
        return aus.UpgradePolicyHandler(
            policy=TestAct.TestPolicy(
                cluster="testing",
                version="4.1.2",
                schedule_type="manual",
            ),
            action=action,
        )

    def test_act_with_diff(self, ocm_map):
        handler = self.create_policy_with_action("create")
        policy = handler.policy
        aus.act(dry_run=False, diffs=[handler], ocm_map=ocm_map)
        assert policy.created
        assert not policy.deleted

    def test_act_delete(self, ocm_map):
        handler = self.create_policy_with_action("delete")
        policy = handler.policy
        aus.act(dry_run=False, diffs=[handler], ocm_map=ocm_map)
        assert not policy.created
        assert policy.deleted


class TestCalculateDiff:
    # testing calculate_diff, not testing locking, see class TestUpgradeLock
    # not testing addon code, see test_ocm_addons_upgrade_scheduler.py
    @staticmethod
    @pytest.fixture
    def ocm_map(mocker):
        mock_ocm_map = mocker.patch(
            "reconcile.aus.ocm_upgrade_scheduler.OCMMap", autospec=True
        )
        map = mock_ocm_map.return_value
        ocm = map.get.return_value
        ocm.name = "foo"
        map.instances.return_value = {"testing": ocm}.keys()
        ocm.get_available_upgrades.return_value = ["4.9.5", "4.10.1"]
        ocm.addons = [{"id": "addon1", "version": {"id": "4.9.5"}}]
        ocm.version_blocked.return_value = False
        return map

    @staticmethod
    @pytest.fixture
    def ocm(ocm_map):
        return ocm_map.get.return_value

    @staticmethod
    @pytest.fixture
    def cluster_upgrade_policy() -> ConfiguredClusterUpgradePolicy:
        return ConfiguredClusterUpgradePolicy(
            **{
                "cluster": "cluster1",
                "current_version": "4.3.0",
                "channel": "stable",
                "schedule": "* * * * *",
                "workloads": ["workload1"],
                "conditions": {"soakDays": 10, "mutexes": ["mutex1"]},
            }
        )

    @staticmethod
    @pytest.fixture
    def addon_upgrade_policy() -> ConfiguredAddonUpgradePolicy:
        return ConfiguredAddonUpgradePolicy(
            **{
                "addon_id": "addon1",
                "cluster": "cluster1",
                "current_version": "4.3.0",
                "schedule": "* * * * *",
                "workloads": ["workload1"],
                "conditions": {"soakDays": 10},
            }
        )

    @staticmethod
    def create_version_data_map(soakDays: int = 11) -> dict[str, Any]:
        return {
            "foo": VersionData(
                **{
                    "check_in": "2021-08-29T18:00:00",
                    "versions": {
                        "4.9.5": {
                            "workloads": {
                                "workload1": {
                                    "soak_days": soakDays,
                                    "reporting": ["cluster1", "cluster2"],
                                },
                            }
                        }
                    },
                }
            ),
        }

    def test_calculate_diff_empty(self, ocm_map: OCMMap):
        x = aus.calculate_diff([], [], ocm_map, {})
        assert not x

    def test_calculate_simple(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm_map: OCMMap
    ):
        x = aus.calculate_diff(
            [], [cluster_upgrade_policy], ocm_map, self.create_version_data_map()
        )

        assert len(x) == 1
        cup = x[0].policy

        assert x[0].action == "create"
        assert cup.cluster == "cluster1"
        assert cup.version == "4.9.5"
        assert cup.schedule_type == "manual"
        assert isinstance(cup, aus.ClusterUpgradePolicy)
        assert cup.gates_to_agree == []

    def test_calculate_not_soaked(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm_map: OCMMap
    ):
        x = aus.calculate_diff(
            [], [cluster_upgrade_policy], ocm_map, self.create_version_data_map(1)
        )

        assert not x

    def test_calculate_blocked(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm_map
    ):
        ocm = ocm_map.get("cluster1")
        ocm.version_blocked.return_value = True
        x = aus.calculate_diff(
            [], [cluster_upgrade_policy], ocm_map, self.create_version_data_map()
        )

        assert not x

    def test_get_upgrades_cluster(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm: OCM
    ):
        v = aus.get_upgrades("", cluster_upgrade_policy, ocm)
        assert v == ["4.9.5", "4.10.1"]

    def test_get_upgrades_addons(
        self, addon_upgrade_policy: ConfiguredAddonUpgradePolicy, ocm: OCM
    ):
        v = aus.get_upgrades("addon1", addon_upgrade_policy, ocm)
        assert v == ["4.9.5"]

    def test_verify_lock_should_skip_false(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm: OCM
    ):
        locked = aus.verify_lock_should_skip(
            cluster_upgrade_policy, {}, ocm, "cluster1"
        )
        assert locked is False

    def test_verify_lock_should_skip_true(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm: OCM
    ):
        locked = aus.verify_lock_should_skip(
            cluster_upgrade_policy, {"mutex1": "cluster1"}, ocm, "cluster1"
        )
        assert locked is True

    def test_verify_schedule_should_skip_cluster_now(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm: OCM
    ):
        now = datetime.now()
        expected = now + timedelta(minutes=6)
        s = aus.verify_schedule_should_skip(
            cluster_upgrade_policy, "cluster1", now, ocm
        )
        assert s == expected.strftime("%Y-%m-%dT%H:%M:00Z")

    def test_verify_schedule_should_skip_addon_now(
        self, addon_upgrade_policy: ConfiguredAddonUpgradePolicy, ocm: OCM
    ):
        now = datetime.now()
        expected = now + timedelta(minutes=2)
        s = aus.verify_schedule_should_skip(
            addon_upgrade_policy, "cluster1", now, ocm, addon_id="addon1"
        )
        assert s == expected.strftime("%Y-%m-%dT%H:%M:00Z")

    def test_verify_schedule_should_skip_cluster_future(
        self, cluster_upgrade_policy: ConfiguredClusterUpgradePolicy, ocm: OCM
    ):
        now = datetime.now()
        next_day = now + timedelta(hours=3)
        cluster_upgrade_policy.schedule = f"* {next_day.hour} * * *"
        s = aus.verify_schedule_should_skip(
            cluster_upgrade_policy, "cluster1", now, ocm
        )

        assert s is None
