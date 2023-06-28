from unittest.mock import Mock

from pytest_mock import MockerFixture

from reconcile.aus import base
from reconcile.aus.base import get_version_data_map
from reconcile.test.ocm.aus.fixtures import build_upgrade_policy
from reconcile.test.ocm.fixtures import build_ocm_info
from reconcile.utils.ocm.ocm import OCMMap
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_get_version_data_map(
    ocm_url: str,
    access_token_url: str,
    mocker: MockerFixture,
    ocm_api: OCMBaseClient,
    state: Mock,
) -> None:
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    mocker.patch.object(
        base,
        "init_state",
        autospec=True,
    ).return_value = state

    ocm_map = OCMMap(
        ocms=[
            build_ocm_info(
                org_name="org-1",
                org_id="org-1-id",
                ocm_url=ocm_url,
                ocm_env_name="prod",
                access_token_url=access_token_url,
            ),
        ]
    )

    version_data = get_version_data_map(
        dry_run=True,
        upgrade_policies=[
            build_upgrade_policy(
                cluster="cluster-1",
                cluster_uuid="cluster-1-uuid",
                current_version="4.12.0",
                workloads=["workload-1"],
                soak_days=1,
            )
        ],
        ocm_map=ocm_map,
        integration="test",
    )

    org_data = version_data.get("prod", "org-1-id")
    assert org_data
    assert org_data.stats and org_data.stats.inherited is None


def test_get_version_data_map_with_inheritance(
    ocm_url: str,
    access_token_url: str,
    mocker: MockerFixture,
    ocm_api: OCMBaseClient,
    state: Mock,
) -> None:
    mocker.patch("reconcile.utils.ocm.ocm.SecretReader")
    mocker.patch.object(
        base,
        "init_state",
        autospec=True,
    ).return_value = state

    ocm_map = OCMMap(
        ocms=[
            build_ocm_info(
                org_name="org-1",
                org_id="org-1-id",
                ocm_url=ocm_url,
                ocm_env_name="prod",
                access_token_url=access_token_url,
                inherit_version_data=[
                    {
                        "name": "org-2",
                        "orgId": "org-2-id",
                        "environment": {
                            "name": "prod",
                        },
                        "publishVersionData": [
                            {
                                "name": "org-1",
                                "orgId": "org-1-id",
                            }
                        ],
                    }
                ],
            ),
        ]
    )

    version_data = get_version_data_map(
        dry_run=True,
        upgrade_policies=[
            build_upgrade_policy(
                cluster="cluster-1",
                cluster_uuid="cluster-1-uuid",
                current_version="4.12.0",
                workloads=["workload-1"],
                soak_days=1,
            )
        ],
        ocm_map=ocm_map,
        integration="test",
    )

    assert version_data.get("prod", "org-1-id").stats.inherited
