from typing import Callable
from unittest.mock import MagicMock, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.deadmanssnitch import (
    CreateSnitchDiffData,
    DeadMansSnitchIntegration,
    DeleteSnitchDiffData,
    DiffData,
    DiffHandler,
    UpdateVaultDiffData,
)
from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DeadMansSnitchSettingsV1,
    VaultSecretV1,
)
from reconcile.gql_definitions.common.clusters_with_dms import (
    ClusterV1,
)
from reconcile.utils.deadmanssnitch_api import (
    DeadMansSnitchApi,
    Snitch,
)


@pytest.fixture
def deadmanssnitch_api() -> MockerFixture:
    return create_autospec(DeadMansSnitchApi)


@pytest.fixture
def deadmanssnitch_settings() -> DeadMansSnitchSettingsV1:
    settings = DeadMansSnitchSettingsV1(
        alertEmail="test_email",
        notesLink="test_link",
        snitchesPath="test_snitches_path",
        tokenCreds=VaultSecretV1(path="test_path", field="test_field"),
    )
    return settings


@pytest.fixture
def vault_mock(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch("reconcile.utils.vault._VaultClient", autospec=True)


@pytest.fixture
def secret_reader(mocker: MockerFixture) -> MockerFixture:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


@pytest.fixture
def cluster_gql_data(gql_class_factory: Callable[..., ClusterV1]) -> list[ClusterV1]:
    return [
        gql_class_factory(
            ClusterV1,
            {"name": "cluster-1", "enableDeadMansSnitch": True},
        ),
        gql_class_factory(
            ClusterV1,
            {"name": "cluster-2", "enableDeadMansSnitch": False},
        ),
    ]


def test_get_current_state(
    secret_reader: MagicMock, deadmanssnitch_api: MockerFixture
) -> None:
    deadmanssnitch_api.get_snitches.return_value = [
        Snitch(
            name="prometheus.test_cluster_1.net",
            token="test",
            href="testc",
            status="healthy",
            alert_type="basic",
            alert_email=["test_mail"],
            interval="15_minute",
            check_in_url="test_url",
            tags=["app-sre"],
            notes="test_notes",
        )
    ]
    clusters = [
        ClusterV1(
            name="test_cluster_1",
            serverUrl="testurl",
            consoleUrl="test_c_url",
            alertmanagerUrl="test_alert_manager",
            managedClusterRoles=True,
            prometheusUrl="test_prom_url",
            enableDeadMansSnitch=True,
        ),
        ClusterV1(
            name="test_cluster_2",
            serverUrl="testurl",
            consoleUrl="test_c_url",
            alertmanagerUrl="test_alert_manager",
            managedClusterRoles=True,
            prometheusUrl="test_prom_url",
            enableDeadMansSnitch=True,
        ),
    ]
    dms_integration = DeadMansSnitchIntegration()
    dms_integration._secret_reader = secret_reader
    current_state = dms_integration.get_current_state(
        deadmanssnitch_api=deadmanssnitch_api,
        clusters=clusters,
        snitch_secret_path="test_path",
    )
    assert current_state["test_cluster_1"].vault_data == "secret"


def test_diff_handler() -> None:
    dms_integration = DeadMansSnitchIntegration()
    diff_data = dms_integration.get_diff(
        current_state={
            "test_cluster_1": Snitch(
                name="test_cluster_1",
                token="test_token",
                status="healthy",
                alert_email=["test_email"],
                notes="test_notes",
                check_in_url="testURL",
                interval="15_minute",
                href="test_href",
                alert_type="test_type",
                tags=["appsre"],
                vault_data="testURL",
            ),
            "test_cluster_3": Snitch(
                name="test_cluster_3",
                token="test_token",
                status="healthy",
                alert_email=["test_email"],
                notes="test_notes",
                check_in_url="testURL2",
                interval="15_minute",
                href="test_href",
                alert_type="test_type",
                tags=["appsre"],
                vault_data="testURL",
            ),
            "test_cluster_5": Snitch(
                name="test_cluster_5",
                token="test_token",
                status="healthy",
                alert_email=["test_email"],
                notes="test_notes",
                check_in_url="testURL",
                interval="15_minute",
                href="test_href",
                alert_type="test_type",
                tags=["appsre"],
                vault_data="testURL2",
            ),
        },
        desired_state=[
            ClusterV1(
                name="test_cluster_1",
                serverUrl="testurl",
                consoleUrl="test_c_url",
                alertmanagerUrl="test_alert_manager",
                managedClusterRoles=True,
                prometheusUrl="test_prom_url",
                enableDeadMansSnitch=True,
            ),
            ClusterV1(
                name="test_cluster_3",
                serverUrl="testurl",
                consoleUrl="test_c_url",
                alertmanagerUrl="test_alert_manager",
                managedClusterRoles=True,
                prometheusUrl="test_prom_url",
                enableDeadMansSnitch=False,
            ),
            ClusterV1(
                name="test_cluster_new",
                serverUrl="testurl",
                consoleUrl="test_c_url",
                alertmanagerUrl="test_alert_manager",
                prometheusUrl="test_prom_url",
                managedClusterRoles=True,
                enableDeadMansSnitch=True,
            ),
            ClusterV1(
                name="test_cluster_5",
                serverUrl="testurl",
                consoleUrl="test_c_url",
                alertmanagerUrl="test_alert_manager",
                prometheusUrl="test_prom_url",
                managedClusterRoles=True,
                enableDeadMansSnitch=True,
            ),
        ],
    )
    expected_output = [
        CreateSnitchDiffData(
            cluster_name="test_cluster_new",
        ),
        DeleteSnitchDiffData(
            cluster_name="test_cluster_3",
            token="test_token",
        ),
        UpdateVaultDiffData(
            cluster_name="test_cluster_5",
            check_in_url="testURL",
        ),
    ]

    assert expected_output == diff_data


def test_apply_diff_for_create(
    vault_mock: MagicMock,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    deadmanssnitch_api: MagicMock,
) -> None:
    diff_data: list[DiffData] = [
        CreateSnitchDiffData(
            cluster_name="create_cluster",
        ),
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(
        deadmanssnitch_api=deadmanssnitch_api,
        vault_client=vault_mock,
        settings=deadmanssnitch_settings,
    )
    dms_integration.apply_diffs(
        dry_run=False, diffs=diff_data, diff_handler=diff_handler
    )
    deadmanssnitch_api.create_snitch.assert_called_once_with({
        "name": "prometheus.create_cluster.devshift.net",
        "alert_type": "Heartbeat",
        "interval": "15_minute",
        "tags": ["app-sre"],
        "alert_email": ["test_email"],
        "notes": "test_link",
    })


def test_apply_diff_for_delete(
    vault_mock: MagicMock,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    deadmanssnitch_api: MagicMock,
) -> None:
    diff_data: list[DiffData] = [
        DeleteSnitchDiffData(cluster_name="create_cluster", token="token_123"),
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(
        deadmanssnitch_api=deadmanssnitch_api,
        vault_client=vault_mock,
        settings=deadmanssnitch_settings,
    )
    dms_integration.apply_diffs(
        dry_run=False, diffs=diff_data, diff_handler=diff_handler
    )
    deadmanssnitch_api.delete_snitch.assert_called_once_with("token_123")


def test_appply_diff_for_update(
    deadmanssnitch_api: MagicMock,
    vault_mock: MagicMock,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
) -> None:
    diff_data: list[DiffData] = [
        UpdateVaultDiffData(
            cluster_name="test_cluster",
            check_in_url="test_secret_url",
        ),
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(
        deadmanssnitch_api=deadmanssnitch_api,
        vault_client=vault_mock,
        settings=deadmanssnitch_settings,
    )
    dms_integration.apply_diffs(
        dry_run=False, diffs=diff_data, diff_handler=diff_handler
    )
    vault_mock.write.assert_called_once_with(
        {
            "path": deadmanssnitch_settings.snitches_path,
            "data": {"deadmanssnitch-test_cluster-url": "test_secret_url"},
        },
        decode_base64=False,
    )


def test_failed_while_apply(
    deadmanssnitch_api: MagicMock,
    mocker: MockerFixture,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
) -> None:
    diff_data: list[DiffData] = [
        UpdateVaultDiffData(
            cluster_name="test_cluster",
            check_in_url="test_secret_url",
        ),
    ]
    vault_mock = mocker.patch(
        "reconcile.utils.vault._VaultClient.write",
        autospec=True,
        side_effect=Exception("mock vault"),
    )
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(
        deadmanssnitch_api=deadmanssnitch_api,
        vault_client=vault_mock,
        settings=deadmanssnitch_settings,
    )

    with pytest.raises(ExceptionGroup) as eg:
        dms_integration.apply_diffs(
            dry_run=False, diffs=diff_data, diff_handler=diff_handler
        )
    assert "Errors occurred while applying diffs" in str(eg.value)
