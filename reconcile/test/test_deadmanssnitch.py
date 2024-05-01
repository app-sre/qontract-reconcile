from unittest.mock import MagicMock, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.deadmanssnitch import (
    DeadMansSnitchIntegration,
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
def deadmanssnitch_api() -> MagicMock:
    return create_autospec(DeadMansSnitchApi)


@pytest.fixture
def deadmanssnitch_settings() -> DeadMansSnitchSettingsV1:
    settings = DeadMansSnitchSettingsV1(
        alertMailAddresses=["test_email"],
        notesLink="test_link",
        snitchesPath="test_snitches_path",
        tokenCreds=VaultSecretV1(path="test_path", field="test_field"),
        tags=["test-tags"],
        alertType="Heartbeat",
        interval="15_minute",
    )
    return settings


@pytest.fixture
def vault_mock(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch("reconcile.utils.vault._VaultClient")


@pytest.fixture
def secret_reader(mocker: MockerFixture) -> MockerFixture:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


def test_get_current_state(
    secret_reader: MagicMock,
    deadmanssnitch_api: MagicMock,
    mocker: MockerFixture,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
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
            prometheusUrl="https://prometheus.test_cluster_1.net",
            enableDeadMansSnitch=True,
        ),
        ClusterV1(
            name="test_cluster_2",
            serverUrl="testurl",
            consoleUrl="test_c_url",
            alertmanagerUrl="test_alert_manager",
            managedClusterRoles=True,
            prometheusUrl="https://prometheus.test_cluster_2.net",
            enableDeadMansSnitch=True,
        ),
    ]
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.__init__"
    ).return_value = None
    dms_integration = DeadMansSnitchIntegration()
    dms_integration._secret_reader = secret_reader
    dms_integration.settings = deadmanssnitch_settings
    current_state = dms_integration.get_current_state(
        deadmanssnitch_api=deadmanssnitch_api,
        clusters=clusters,
        vault_snitch_map={"deadmanssnitch-test_cluster_1-url": "secret"},
    )
    assert current_state["test_cluster_1"].vault_data == "secret"


def test_integration_for_create(
    vault_mock: MagicMock,
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    mocker: MockerFixture,
    secret_reader: MagicMock,
) -> None:
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.__init__"
    ).return_value = None
    dms_integration = DeadMansSnitchIntegration()
    secret_reader.read_all.return_value = {}
    dms_integration._secret_reader = secret_reader
    dms_integration.settings = deadmanssnitch_settings
    dms_integration.vault_client = vault_mock
    mocker.patch("reconcile.deadmanssnitch.get_clusters_with_dms").return_value = [
        ClusterV1(
            name="create_cluster",
            prometheusUrl="https://prometheus.create_cluster.devshift.net",
            enableDeadMansSnitch=True,
            alertmanagerUrl="alertmanager.create_cluster.devshift.net",
            managedClusterRoles=True,
            serverUrl="testurl",
            consoleUrl="test_console",
        )
    ]
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchApi.get_snitches"
    ).return_value = []
    mock_create_snitch = mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.create_snitch"
    )
    mock_create_snitch.return_value = Snitch(
        name="prometheus.create_cluster.devshift.net",
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
    dms_integration.run(dry_run=False)
    mock_create_snitch.assert_called_once()


def test_integration_for_delete(
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    vault_mock: MagicMock,
    mocker: MockerFixture,
    secret_reader: MagicMock,
) -> None:
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.__init__"
    ).return_value = None
    dms_integration = DeadMansSnitchIntegration()
    secret_reader.read_all.return_value = {"deadmanssnitch-create_cluster-url": "test"}
    dms_integration._secret_reader = secret_reader
    dms_integration.settings = deadmanssnitch_settings
    dms_integration.vault_client = vault_mock
    mocker.patch("reconcile.deadmanssnitch.get_clusters_with_dms").return_value = [
        ClusterV1(
            name="create_cluster",
            prometheusUrl="https://prometheus.create_cluster.devshift.net",
            enableDeadMansSnitch=False,
            alertmanagerUrl="alertmanager.create_cluster.devshift.net",
            managedClusterRoles=True,
            serverUrl="testurl",
            consoleUrl="test_console",
        )
    ]
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchApi.get_snitches"
    ).return_value = [
        Snitch(
            name="prometheus.create_cluster.devshift.net",
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
    mock_delete_snitch = mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchApi.delete_snitch"
    )
    mock_delete_snitch.return_value = None
    dms_integration.run(dry_run=False)
    mock_delete_snitch.assert_called_once_with("test")


def test_integration_for_update_vault(
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    vault_mock: MagicMock,
    mocker: MockerFixture,
    secret_reader: MagicMock,
) -> None:
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.__init__"
    ).return_value = None
    dms_integration = DeadMansSnitchIntegration()
    secret_reader.read_all.return_value = {"deadmanssnitch-test_cluster-url": "test"}
    dms_integration._secret_reader = secret_reader
    dms_integration.settings = deadmanssnitch_settings
    dms_integration.vault_client = vault_mock
    mocker.patch("reconcile.deadmanssnitch.get_clusters_with_dms").return_value = [
        ClusterV1(
            name="test_cluster",
            prometheusUrl="https://prometheus.create_cluster.devshift.net",
            enableDeadMansSnitch=True,
            alertmanagerUrl="alertmanager.create_cluster.devshift.net",
            managedClusterRoles=True,
            serverUrl="testurl",
            consoleUrl="test_console",
        )
    ]
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchApi.get_snitches"
    ).return_value = [
        Snitch(
            name="prometheus.create_cluster.devshift.net",
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
    dms_integration.run(dry_run=False)
    data = {"deadmanssnitch-test_cluster-url": "test_url"}
    vault_mock.write.assert_called_once_with(
        {
            "path": deadmanssnitch_settings.snitches_path,
            "data": data,
        },
        decode_base64=False,
    )


def test_integration_while_failed(
    deadmanssnitch_settings: DeadMansSnitchSettingsV1,
    vault_mock: MagicMock,
    mocker: MockerFixture,
    secret_reader: MagicMock,
) -> None:
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.__init__"
    ).return_value = None
    dms_integration = DeadMansSnitchIntegration()
    dms_integration._secret_reader = secret_reader
    dms_integration.settings = deadmanssnitch_settings
    dms_integration.vault_client = vault_mock
    mocker.patch("reconcile.deadmanssnitch.get_clusters_with_dms").return_value = [
        ClusterV1(
            name="create_cluster",
            prometheusUrl="https://prometheus.create_cluster.devshift.net",
            enableDeadMansSnitch=True,
            alertmanagerUrl="alertmanager.create_cluster.devshift.net",
            managedClusterRoles=True,
            serverUrl="testurl",
            consoleUrl="test_console",
        )
    ]
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchApi.get_snitches"
    ).return_value = []
    mocker.patch(
        "reconcile.deadmanssnitch.DeadMansSnitchIntegration.create_snitch",
        side_effect=Exception("mock vault"),
    )
    with pytest.raises(ExceptionGroup):
        dms_integration.run(dry_run=False)
