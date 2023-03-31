from copy import deepcopy

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ocm import (
    OCM,
    OCMMap,
    Sector,
    SectorConfigError,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def ocm_url() -> str:
    return "http://ocm.test"


@pytest.fixture
def cluster() -> str:
    return "cluster-1"


@pytest.fixture
def cluster_id(cluster: str) -> str:
    return f"{cluster}-id"


@pytest.fixture
def ocm(mocker: MockerFixture, ocm_url: str, cluster: str, cluster_id: str) -> OCM:
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_access_token")
    mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM.whoami")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_blocked_versions")
    mocker.patch("reconcile.utils.ocm.OCM._init_version_gates")
    ocm_client = OCMBaseClient("url", "tid", "turl", "cid")
    ocm = OCM("name", "org_id", ocm_client)
    ocm._ocm_client._url = ocm_url
    ocm.cluster_ids = {cluster: cluster_id}
    return ocm


def test_get_cluster_aws_account_id_none(mocker, ocm):
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = []
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result is None


def test_get_cluster_aws_account_id_ok(mocker, ocm):
    console_url = (
        "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    )
    expected = "12345"
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = [(None, None, None, console_url)]
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result == expected


@pytest.fixture
def clusters_by_readiness():
    return [
        (
            {
                "product": {"id": "osd"},
                "managed": False,
                "state": "ready",
                "storage_quota": 42,
            },
            False,
        ),
        (
            {
                "product": {"id": "osd"},
                "managed": True,
                "state": "ready",
                "storage_quota": 42,
            },
            True,
        ),
        (
            {
                "product": "osd",
                "managed": True,
                "state": "not ready",
                "storage_quota": 42,
            },
            False,
        ),
        # ROSA-like cluster
        ({"product": {"id": "rosa"}, "managed": True, "state": "ready"}, True),
    ]


def test__ready_for_app_interface(clusters_by_readiness, ocm):
    for cluster, readiness in clusters_by_readiness:
        assert ocm._ready_for_app_interface(cluster) == readiness


def test_get_version_gate(ocm):
    ocm.version_gates = [
        {"version_raw_id_prefix": "4.9", "sts_only": True},
        {"version_raw_id_prefix": "4.9", "sts_only": False},
        {"version_raw_id_prefix": "4.10", "sts_only": False},
    ]
    gates = ocm.get_version_gates("4.9")
    assert gates == [{"version_raw_id_prefix": "4.9", "sts_only": False}]
    gates = ocm.get_version_gates("4.9", sts_only=True)
    assert gates == [{"version_raw_id_prefix": "4.9", "sts_only": True}]
    assert len(ocm.get_version_gates("4.8")) == 0


def test_sector_validate_dependencies(ocm):
    sector1 = Sector(name="sector1", ocm=ocm)
    sector2 = Sector(name="sector2", ocm=ocm, dependencies=[sector1])
    sector3 = Sector(name="sector3", ocm=ocm, dependencies=[sector2])
    assert sector3.validate_dependencies()

    # zero-level loop sector1 -> sector1
    sector1 = Sector(name="sector1", ocm=ocm)
    sector1.dependencies = [sector1]
    with pytest.raises(SectorConfigError):
        sector1.validate_dependencies()

    # single-level loop sector2 -> sector1 -> sector2
    sector1 = Sector(name="sector1", ocm=ocm)
    sector2 = Sector(name="sector2", ocm=ocm, dependencies=[sector1])
    sector1.dependencies = [sector2]
    with pytest.raises(SectorConfigError):
        sector2.validate_dependencies()

    # greater-level loop sector3 -> sector2 -> sector1 -> sector3
    sector1 = Sector(name="sector1", ocm=ocm)
    sector2 = Sector(name="sector2", ocm=ocm, dependencies=[sector1])
    sector3 = Sector(name="sector3", ocm=ocm, dependencies=[sector2])
    sector1.dependencies = [sector3]
    with pytest.raises(SectorConfigError):
        sector3.validate_dependencies()


def test_ocm_map_upgrade_policies_sector(ocm, mocker):
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    sectors = [
        {"name": "s1"},
        {"name": "s2", "dependencies": [{"name": "s1"}]},
        {"name": "s3", "dependencies": [{"ocm": {"name": "ocm1"}, "name": "s1"}]},
    ]
    ocm1_info = {
        "name": "ocm1",
        "sectors": sectors,
        "orgId": "orgId1",
        "environment": {
            "name": "name",
            "url": "u",
            "accessTokenClientId": "atci",
            "accessTokenUrl": "atu",
            "accessTokenClientSecret": "atcs",
        },
    }
    c1 = {
        "name": "c1",
        "ocm": ocm1_info,
        "upgradePolicy": {"workload": "w1"},
    }
    c2 = {
        "name": "c2",
        "ocm": ocm1_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s2"}},
    }

    # second org, using the same sector names
    ocm2_info = deepcopy(ocm1_info)
    ocm2_info["name"] = "ocm2"
    ocm2_info["orgId"] = ("orgId2",)
    c3 = {
        "name": "c3",
        "ocm": ocm2_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s3"}},
    }

    mocker.patch("reconcile.utils.ocm.OCM.is_ready").return_value = True
    ocm_map = OCMMap(clusters=[c1, c2, c3])
    assert "ocm1" in ocm_map.ocm_map
    assert "ocm2" in ocm_map.ocm_map

    # all sectors are reported, even the ones without clusters
    ocm1 = ocm_map["ocm1"]
    assert len(ocm1.sectors) == 3

    ocm2 = ocm_map["ocm2"]
    assert len(ocm2.sectors) == 3

    # no dependencies
    s1 = Sector(name="s1", ocm=ocm1)
    assert ocm1.sectors["s1"] == s1

    # partial dependency definition, without ocm org. defaulting to sector's org
    s2 = Sector(name="s2", ocm=ocm1, dependencies=[s1], cluster_infos=[c2])
    assert ocm1.sectors["s2"] == s2
