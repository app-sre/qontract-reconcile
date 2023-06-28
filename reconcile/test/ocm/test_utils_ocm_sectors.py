from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ocm import (
    OCM,
    OCMMap,
    Sector,
    SectorConfigError,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_sector_validate_dependencies(ocm: OCM) -> None:
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


def build_ocm_info(
    org_name: str, ocm_url: str, access_token_url: str
) -> dict[str, Any]:
    return {
        "name": org_name,
        "sectors": [
            {"name": "s1"},
            {"name": "s2", "dependencies": [{"name": "s1"}]},
            {"name": "s3", "dependencies": [{"ocm": {"name": "ocm1"}, "name": "s1"}]},
        ],
        "orgId": org_name,
        "environment": {
            "name": "name",
            "url": ocm_url,
            "accessTokenClientId": "atci",
            "accessTokenUrl": access_token_url,
            "accessTokenClientSecret": {
                "path": "/path/to/secret",
                "field": "field",
                "version": None,
                "format": None,
            },
        },
    }


def test_ocm_map_upgrade_policies_sector(
    ocm_url: str, access_token_url: str, ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    ocm_org1_info = build_ocm_info("org-1", ocm_url, access_token_url)
    c1 = {
        "name": "c1",
        "ocm": ocm_org1_info,
        "upgradePolicy": {"workload": "w1"},
    }
    c2 = {
        "name": "c2",
        "ocm": ocm_org1_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s2"}},
    }

    # second org, using the same sector names
    ocm_org2_info = build_ocm_info("org-2", ocm_url, access_token_url)
    c3 = {
        "name": "c3",
        "ocm": ocm_org2_info,
        "upgradePolicy": {"workload": "w1", "conditions": {"sector": "s3"}},
    }

    mocker.patch("reconcile.utils.ocm.OCM.is_ready").return_value = True
    ocm_map = OCMMap(clusters=[c1, c2, c3])
    assert "org-1" in ocm_map.ocm_map
    assert "org-2" in ocm_map.ocm_map

    # all sectors are reported, even the ones without clusters
    ocm1 = ocm_map["org-1"]
    assert len(ocm1.sectors) == 3

    ocm2 = ocm_map["org-2"]
    assert len(ocm2.sectors) == 3

    # no dependencies
    s1 = Sector(name="s1", ocm=ocm1)
    assert ocm1.sectors["s1"] == s1

    # partial dependency definition, without ocm org. defaulting to sector's org
    s2 = Sector(name="s2", ocm=ocm1, dependencies=[s1], cluster_infos=[c2])
    assert ocm1.sectors["s2"] == s2
