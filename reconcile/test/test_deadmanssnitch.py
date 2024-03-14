import json
from typing import Callable
from unittest.mock import MagicMock, create_autospec

import httpretty
import pytest
from pytest_mock import MockerFixture

from reconcile.deadmanssnitch import (
    Action,
    DeadMansSnitchIntegration,
    DiffData,
    DiffHandler,
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

TOKEN = "test_token"
FAKE_URL = "https://fake.deadmanssnitch.com/v1/snitches"
@pytest.fixture
def deadmanssnitch_api() -> DeadMansSnitchApi:
    return DeadMansSnitchApi(token=TOKEN, url=FAKE_URL)


@pytest.fixture
def deadmanssnitch_settings() -> DeadMansSnitchSettingsV1:
    settings = DeadMansSnitchSettingsV1(
        alertEmail="test_email",
        notesLink="test_link",
        snitchesPath="test_snitches_path",
        tokenCreds=VaultSecretV1(path="test_path", field="test_field")
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

@httpretty.activate(allow_net_connect=False)
def test_get_current_state(secret_reader: MagicMock, deadmanssnitch_api: DeadMansSnitchApi) -> None:
    httpretty.register_uri(
        httpretty.GET,
        f"{deadmanssnitch_api.url}?tags=appsre",
            body=json.dumps([{
            "token": "test",
            "href": "testc",
            "name": "prometheus.test_cluster_1.net",
            "tags": ["app-sre"],
            "notes": "test_notes",
            "status": "healthy",
            "check_in_url": "test_url",
            "type": {"interval": "15_minute"},
            "interval": "15_minute",
            "alert_type": "basic",
            "alert_email": ["test_mail"]
        }]),
        content_type="text/json",
        status=200,
    )

    clusters = [
        ClusterV1(
            name="test_cluster_1",
            serverUrl="testurl",
            consoleUrl="test_c_url",
            alertmanagerUrl="test_alert_manager",
            managedClusterRoles=True,
            prometheusUrl="test_prom_url",
            enableDeadMansSnitch=True
        ),
         ClusterV1(
            name="test_cluster_2",
            serverUrl="testurl",
            consoleUrl="test_c_url",
            alertmanagerUrl="test_alert_manager",
            managedClusterRoles=True,
            prometheusUrl="test_prom_url",
            enableDeadMansSnitch=True
        )
    ]
    dms_integration = DeadMansSnitchIntegration()
    dms_integration._secret_reader = secret_reader
    current_state = dms_integration.get_current_state(deadmanssnitch_api=deadmanssnitch_api, clusters=clusters, snitch_secret_path="test_path")
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
            )
        },
        desired_state=[
            ClusterV1(
                name="test_cluster_1",
                serverUrl="testurl",
                consoleUrl="test_c_url",
                alertmanagerUrl="test_alert_manager",
                managedClusterRoles=True,
                prometheusUrl="test_prom_url",
                enableDeadMansSnitch=True
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
            )
        ],
    )
    expected_output = [
        DiffData(
            cluster_name="test_cluster_new",
            action=Action.create_snitch,
        ),
        DiffData(
            cluster_name="test_cluster_3",
            data="test_token",
            action=Action.delete_snitch,
        ),
        DiffData(
            cluster_name="test_cluster_5",
            data="testURL",
            action=Action.update_vault,
        ),
    ]

    expected_output_map = [data.__dict__ for data in expected_output]
    diff_data_map = [data.__dict__ for data in diff_data]
    assert diff_data_map == expected_output_map

def test_apply_diff_for_create(vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1) -> None:
    diff_data = [
        DiffData(
            cluster_name="create_cluster",
            action=Action.create_snitch,
        ),
    ]
    mocked_deadmanssnitch_api = create_autospec(DeadMansSnitchApi)
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=mocked_deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    mocked_deadmanssnitch_api.create_snitch.assert_called_once_with(
        {
            "name": "prometheus.create_cluster.devshift.net",
            "alert_type": "Heartbeat",
            "interval": "15_minute",
            "tags": ["app-sre"],
            "alert_email": ["test_email"],
            "notes": "test_link",
        }
    )

def test_apply_diff_for_delete(vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1) -> None:
    diff_data = [
        DiffData(
            cluster_name="create_cluster",
            action=Action.delete_snitch,
            data="token_123"
        ),
    ]
    mocked_deadmanssnitch_api = create_autospec(DeadMansSnitchApi)
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=mocked_deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    mocked_deadmanssnitch_api.delete_snitch.assert_called_once_with(
        "token_123"
    )


def test_appply_diff_for_update(deadmanssnitch_api: DeadMansSnitchApi, vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1) -> None:
    diff_data = [
        DiffData(
            cluster_name="test_cluster",
            action=Action.update_vault,
            data="test_secret_url",
        ),
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    vault_mock.write.assert_called_once_with(
        {"path": f"{deadmanssnitch_settings.snitches_path}/deadmanssnitch-test_cluster-url", "data": "test_secret_url"}
    )
