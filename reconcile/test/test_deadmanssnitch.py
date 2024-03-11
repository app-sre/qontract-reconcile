import json
from typing import Callable
from unittest.mock import MagicMock

import httpretty
import pytest
from pytest_mock import MockerFixture

from reconcile.deadmanssnitch import (
    DeadMansSnitchIntegration,
    DiffHandler,
)
from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DeadMansSnitchSettingsV1,
    VaultSecretV1,
)
from reconcile.gql_definitions.common.clusters_with_dms import (
    ClusterV1,
)
from reconcile.utils.deadmanssnitch_api import DeadMansSnitchApi

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
def test_get_current_state(secret_reader: MagicMock, deadmanssnitch_api: DeadMansSnitchApi):
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
    assert current_state[0].get("vault_snitch_value") == "secret"

def test_diff_handler(deadmanssnitch_api: DeadMansSnitchApi, vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1):
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    diff_data = dms_integration.get_diff(
        current_states=[
            {
                "cluster_name": "test_cluster_1",
                "check_in_url": "testURL",
                "vault_snitch_value": "testURL"
            },
            {
                "cluster_name": "test_cluster_3",
                "check_in_url": "testURL2",
                "token": "test_token"
            },
            {
                "cluster_name": "test_cluster_5",
                "check_in_url": "testURL",
                "vault_snitch_value": "testURL2"
            }
        ],
        desired_states=[
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
        diff_handler=diff_handler,
    )
    expected_output = [
        {
            "action": "delete_snitch",
            "cluster_name": "test_cluster_3",
            "token": "test_token"
        },
        {
            "action": "update_vault",
            "cluster_name": "test_cluster_5",
            "snitch_url": "testURL"
        },
        {
            "action": "create_snitch",
            "cluster_name": "test_cluster_new"
        },
    ]
    assert diff_data == expected_output

@httpretty.activate(allow_net_connect=False)
def test_apply_diff_for_create(deadmanssnitch_api: DeadMansSnitchApi, vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1):
    httpretty.register_uri(
        httpretty.POST,
        deadmanssnitch_api.url,
        body=json.dumps({
            "token": "test_token",
            "href": "testc",
            "name": "prometheus.create_cluster.net",
            "tags": ["app-sre"],
            "notes": "test_notes",
            "status": "healthy",
            "check_in_url": "test_url",
            "type": {"interval": "15_minute"},
            "interval": "15_minute",
            "alert_type": "basic",
            "alert_email": ["test_mail"]
        }),
        content_type="text/json",
        status=201,
    )
    diff_data = [
        {
            "cluster_name": "create_cluster",
            "action": "create_snitch",
        },
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    assert httpretty.last_request().headers.get("Authorization") == "Basic dGVzdF90b2tlbjo="  # base 64 encoded form of "test_token"

@httpretty.activate(allow_net_connect=False)
def test_apply_diff_for_delete(deadmanssnitch_api: DeadMansSnitchApi, vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1):
    httpretty.register_uri(
        httpretty.DELETE,
        f"{deadmanssnitch_api.url}/token_123",
        status=200,
    )
    diff_data = [
        {
            "cluster_name": "create_cluster",
            "action": "delete_snitch",
            "token": "token_123"
        },
    ]
    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    assert httpretty.last_request().headers.get("Authorization") == "Basic dGVzdF90b2tlbjo="  # base 64 encoded form of "test_token"


def test_appply_diff_for_update(deadmanssnitch_api: DeadMansSnitchApi, vault_mock: MagicMock, deadmanssnitch_settings: DeadMansSnitchSettingsV1):
    diff_data = [
        {
            "cluster_name": "test_cluster",
            "action": "update_vault",
            "snitch_url": "test_secret_url"
        },
    ]

    dms_integration = DeadMansSnitchIntegration()
    diff_handler = DiffHandler(deadmanssnitch_api=deadmanssnitch_api, vault_client=vault_mock, settings=deadmanssnitch_settings)
    dms_integration.apply_diffs(dry_run=False, diffs=diff_data, diff_handler=diff_handler)
    vault_mock.write.assert_called_once_with(
        {"path": f"{deadmanssnitch_settings.snitches_path}/deadmanssnitch-test_cluster-url", "data": "test_secret_url"}
    )
