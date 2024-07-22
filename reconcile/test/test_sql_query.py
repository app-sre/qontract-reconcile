from collections.abc import Callable
from unittest.mock import create_autospec

import pytest
from pytest_mock import MockFixture

import reconcile.sql_query as intg
from reconcile.gql_definitions.common.smtp_client_settings import SmtpSettingsV1
from reconcile.sql_query import split_long_query
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.state import State


@pytest.mark.parametrize(
    "q, size, expected",
    [
        ("test", 1, ["t", "e", "s", "t"]),
        (
            "this is a longer string",
            3,
            ["thi", "s i", "s a", " lo", "nge", "r s", "tri", "ng"],
        ),
        ("testtest", 100, ["testtest"]),
    ],
)
def test_split_long_query(q, size, expected):
    assert split_long_query(q, size) == expected


@pytest.fixture
def smtp_settings(
    gql_class_factory: Callable[..., SmtpSettingsV1],
) -> SmtpSettingsV1:
    return gql_class_factory(
        SmtpSettingsV1,
        {
            "mailAddress": "some_address",
            "timeout": 30,
            "credentials": {
                "path": "some-path",
            },
        },
    )


@pytest.fixture
def smtp_server_connection_info() -> dict:
    return {
        "server": "some-host",
        "port": 1234,
        "username": "some-username",
        "password": "some-password",
    }


@pytest.fixture
def sql_query() -> dict:
    return {
        "name": "some-query",
        "delete": None,
        "identifier": "rds-id",
        "query": None,
        "queries": ["SELECT * FROM table;"],
        "namespace": {
            "name": "some-namespace",
            "managedExternalResources": True,
            "externalResources": [
                {
                    "provider": "aws",
                    "provisioner": {
                        "name": "some-provisioner",
                    },
                    "resources": [
                        {
                            "provider": "rds",
                            "identifier": "rds-id",
                        }
                    ],
                }
            ],
            "app": {
                "name": "some-app",
            },
            "environment": {
                "name": "some-env",
            },
            "cluster": {
                "name": "some-cluster",
            },
        },
        "overrides": None,
        "output": "stdout",
    }


def setup_mocks(
    mocker: MockFixture,
    smtp_settings: SmtpSettingsV1,
    smtp_server_connection_info: dict,
    sql_query: dict,
    state: dict,
    time: float = 0.0,
    current_items: dict[str, list[str]] | None = None,
) -> dict:
    mocked_queries = mocker.patch("reconcile.sql_query.queries")
    mocked_queries.get_app_interface_settings.return_value = {}
    mocked_queries.get_app_interface_sql_queries.return_value = [sql_query]
    mocked_state = create_autospec(State)
    mocked_state.ls.return_value = [f"/{k}" for k in state]
    mocked_state.__getitem__.side_effect = lambda x: state[x]
    mocked_secret_reader = mocker.patch("reconcile.sql_query.SecretReader")
    mocked_secret_reader.return_value.read_all_secret.return_value = (
        smtp_server_connection_info
    )
    mocker.patch("reconcile.sql_query.init_state", return_value=mocked_state)
    mocker.patch(
        "reconcile.sql_query.typed_queries.smtp.settings", return_value=smtp_settings
    )
    mocked_ts = mocker.patch("reconcile.sql_query.Terrascript")
    mocked_ts.return_value.init_values.return_value = {}
    mocked_ob = mocker.patch("reconcile.sql_query.openshift_base")

    mocked_oc_map = mocker.patch("reconcile.sql_query.OC_Map", autospec=True)
    mocked_oc_client = create_autospec(OCCli)
    mocked_oc_client.get_items.side_effect = lambda kind, **_: [
        {"kind": kind, "metadata": {"name": name}}
        for name in (current_items or {}).get(kind, [])
    ]
    mocked_oc_map.return_value.__enter__.return_value.get_cluster.return_value = (
        mocked_oc_client
    )

    mocked_time = mocker.patch("reconcile.sql_query.time")
    mocked_time.time.return_value = time

    return {
        "mocked_queries": mocked_queries,
        "mocked_state": mocked_state,
        "mocked_ob": mocked_ob,
    }


def _verify_publish_metrics(
    ri: ResourceInventory,
    integration: str,
    expected_metrics: dict[tuple[str, str, str, str], int],
) -> None:
    assert integration == "sql-query"
    metrics = {
        (cluster, namespace, kind, state): len(data[state])
        for cluster, namespace, kind, data in ri
        for state in ("current", "desired")
    }
    assert expected_metrics == metrics


def test_run_with_new_sql_query(
    mocker: MockFixture,
    smtp_settings: SmtpSettingsV1,
    smtp_server_connection_info: dict,
    sql_query: dict,
) -> None:
    mocks = setup_mocks(
        mocker=mocker,
        smtp_settings=smtp_settings,
        smtp_server_connection_info=smtp_server_connection_info,
        sql_query=sql_query,
        state={},
    )

    intg.run(False)

    mocks["mocked_ob"].apply.assert_called()
    assert mocks["mocked_ob"].apply.call_count == 4
    mocks["mocked_ob"].delete.assert_not_called()

    mocks["mocked_ob"].publish_metrics.assert_called_once()
    ri, integration = mocks["mocked_ob"].publish_metrics.call_args[0]
    expected_metrics = {
        ("some-cluster", "some-namespace", "ConfigMap", "current"): 0,
        ("some-cluster", "some-namespace", "ConfigMap", "desired"): 2,
        ("some-cluster", "some-namespace", "ServiceAccount", "current"): 0,
        ("some-cluster", "some-namespace", "ServiceAccount", "desired"): 1,
        ("some-cluster", "some-namespace", "Job", "current"): 0,
        ("some-cluster", "some-namespace", "Job", "desired"): 1,
        ("some-cluster", "some-namespace", "CronJob", "current"): 0,
        ("some-cluster", "some-namespace", "CronJob", "desired"): 0,
        ("some-cluster", "some-namespace", "Secret", "current"): 0,
        ("some-cluster", "some-namespace", "Secret", "desired"): 0,
    }
    _verify_publish_metrics(ri, integration, expected_metrics)


def test_run_with_deleted_sql_query(
    mocker: MockFixture,
    smtp_settings: SmtpSettingsV1,
    smtp_server_connection_info: dict,
    sql_query: dict,
) -> None:
    mocks = setup_mocks(
        mocker=mocker,
        smtp_settings=smtp_settings,
        smtp_server_connection_info=smtp_server_connection_info,
        sql_query=sql_query,
        state={"some-query": "DONE"},
    )

    intg.run(False)

    mocks["mocked_ob"].apply.assert_not_called()
    mocks["mocked_ob"].delete.assert_not_called()

    mocks["mocked_ob"].publish_metrics.assert_called_once()
    ri, integration = mocks["mocked_ob"].publish_metrics.call_args[0]
    expected_metrics = {
        ("some-cluster", "some-namespace", "ConfigMap", "current"): 0,
        ("some-cluster", "some-namespace", "ConfigMap", "desired"): 0,
        ("some-cluster", "some-namespace", "ServiceAccount", "current"): 0,
        ("some-cluster", "some-namespace", "ServiceAccount", "desired"): 0,
        ("some-cluster", "some-namespace", "Job", "current"): 0,
        ("some-cluster", "some-namespace", "Job", "desired"): 0,
        ("some-cluster", "some-namespace", "CronJob", "current"): 0,
        ("some-cluster", "some-namespace", "CronJob", "desired"): 0,
        ("some-cluster", "some-namespace", "Secret", "current"): 0,
        ("some-cluster", "some-namespace", "Secret", "desired"): 0,
    }
    _verify_publish_metrics(ri, integration, expected_metrics)


@pytest.fixture
def current_items() -> dict[str, list[str]]:
    return {
        "ConfigMap": ["some-query-gpg-key", "some-query-q00000c00000"],
        "ServiceAccount": ["some-query"],
        "Job": ["some-query"],
    }


def test_run_with_pending_deletion_sql_query(
    mocker: MockFixture,
    smtp_settings: SmtpSettingsV1,
    smtp_server_connection_info: dict,
    sql_query: dict,
    current_items: dict[str, list[str]],
) -> None:
    mocks = setup_mocks(
        mocker=mocker,
        smtp_settings=smtp_settings,
        smtp_server_connection_info=smtp_server_connection_info,
        sql_query=sql_query,
        state={"some-query": 0},
        time=604800.0,
        current_items=current_items,
    )

    intg.run(False, enable_deletion=True)

    mocks["mocked_ob"].apply.assert_not_called()
    mocks["mocked_ob"].delete.assert_called()
    assert mocks["mocked_ob"].delete.call_count == 4
    mocks["mocked_state"].__setitem__.assert_called_once_with("some-query", "DONE")

    mocks["mocked_ob"].publish_metrics.assert_called_once()
    ri, integration = mocks["mocked_ob"].publish_metrics.call_args[0]
    expected_metrics = {
        ("some-cluster", "some-namespace", "ConfigMap", "current"): 2,
        ("some-cluster", "some-namespace", "ConfigMap", "desired"): 0,
        ("some-cluster", "some-namespace", "ServiceAccount", "current"): 1,
        ("some-cluster", "some-namespace", "ServiceAccount", "desired"): 0,
        ("some-cluster", "some-namespace", "Job", "current"): 1,
        ("some-cluster", "some-namespace", "Job", "desired"): 0,
        ("some-cluster", "some-namespace", "CronJob", "current"): 0,
        ("some-cluster", "some-namespace", "CronJob", "desired"): 0,
        ("some-cluster", "some-namespace", "Secret", "current"): 0,
        ("some-cluster", "some-namespace", "Secret", "desired"): 0,
    }
    _verify_publish_metrics(ri, integration, expected_metrics)


def test_run_with_active_sql_query(
    mocker: MockFixture,
    smtp_settings: SmtpSettingsV1,
    smtp_server_connection_info: dict,
    sql_query: dict,
    current_items: dict[str, list[str]],
) -> None:
    mocks = setup_mocks(
        mocker=mocker,
        smtp_settings=smtp_settings,
        smtp_server_connection_info=smtp_server_connection_info,
        sql_query=sql_query,
        state={"some-query": 0},
        time=604800.0 - 1,
    )

    intg.run(False, enable_deletion=True)

    mocks["mocked_ob"].apply.assert_not_called()
    mocks["mocked_ob"].delete.assert_not_called()

    mocks["mocked_ob"].publish_metrics.assert_called_once()
    ri, integration = mocks["mocked_ob"].publish_metrics.call_args[0]
    expected_metrics = {
        ("some-cluster", "some-namespace", "ConfigMap", "current"): 2,
        ("some-cluster", "some-namespace", "ConfigMap", "desired"): 2,
        ("some-cluster", "some-namespace", "ServiceAccount", "current"): 1,
        ("some-cluster", "some-namespace", "ServiceAccount", "desired"): 1,
        ("some-cluster", "some-namespace", "Job", "current"): 1,
        ("some-cluster", "some-namespace", "Job", "desired"): 1,
        ("some-cluster", "some-namespace", "CronJob", "current"): 0,
        ("some-cluster", "some-namespace", "CronJob", "desired"): 0,
        ("some-cluster", "some-namespace", "Secret", "current"): 0,
        ("some-cluster", "some-namespace", "Secret", "desired"): 0,
    }
    _verify_publish_metrics(ri, integration, expected_metrics)
