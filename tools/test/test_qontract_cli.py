from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from gitlab.const import PipelineStatus

from reconcile.utils.early_exit_cache import CacheHeadResult, CacheKey, CacheStatus
from reconcile.utils.mr.labels import (
    HOLD,
    LGTM,
    PIPELINE_ERROR,
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
)
from tools import qontract_cli

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _make_cluster(name: str, vpc_cidr: str, account_name: str = "acc") -> dict:
    return {
        "name": name,
        "network": {"vpc": vpc_cidr},
        "spec": {"account": {"name": account_name}},
        "peering": None,
        "description": None,
    }


@pytest.fixture
def env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", "some-bucket")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", "some-account")


@pytest.fixture
def mock_queries(mocker: MockerFixture) -> None:
    mocker.patch("tools.qontract_cli.queries", autospec=True)


@pytest.fixture
def mock_state(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.init_state", autospec=True)


@pytest.fixture
def mock_early_exit_cache(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.EarlyExitCache", autospec=True)


@pytest.fixture
def mock_get_app_interface_vault_settings(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.get_app_interface_vault_settings")


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.create_secret_reader")


def test_state_ls_with_integration(
    env_vars: None, mock_queries: None, mock_state: Mock
) -> None:
    runner = CliRunner()

    mock_state.return_value.ls.return_value = [
        "/key1",
        "/nested/key2",
    ]

    result = runner.invoke(qontract_cli.state, "ls integration")
    assert result.exit_code == 0
    assert (
        result.output
        == """INTEGRATION    KEY
-------------  -----------
integration    key1
integration    nested/key2
"""
    )


def test_state_ls_without_integration(
    env_vars: None, mock_queries: None, mock_state: Mock
) -> None:
    runner = CliRunner()

    mock_state.return_value.ls.return_value = [
        "/integration1/key1",
        "/integration2/nested/key2",
    ]

    result = runner.invoke(qontract_cli.state, "ls")
    assert result.exit_code == 0
    assert (
        result.output
        == """INTEGRATION    KEY
-------------  -----------
integration1   key1
integration2   nested/key2
"""
    )


def test_early_exit_cache_get(
    env_vars: None, mock_queries: None, mock_early_exit_cache: Mock
) -> None:
    runner = CliRunner()
    mock_early_exit_cache.build.return_value.__enter__.return_value.get.return_value = (
        "some value"
    )

    result = runner.invoke(
        qontract_cli.early_exit_cache, "get -i a -v b --dry-run -c {} -s shard-1"
    )
    assert result.exit_code == 0
    assert result.output == "some value\n"


def test_early_exit_cache_set(
    env_vars: None, mock_queries: None, mock_early_exit_cache: Mock
) -> None:
    runner = CliRunner()

    result = runner.invoke(
        qontract_cli.early_exit_cache,
        "set -i a -v b --no-dry-run -c {} -s shard-1 -p {} -l log -t 30 -d digest",
    )
    assert result.exit_code == 0
    mock_early_exit_cache.build.return_value.__enter__.return_value.set.assert_called()


def test_early_exit_cache_head(
    env_vars: None, mock_queries: None, mock_early_exit_cache: Mock
) -> None:
    runner = CliRunner()

    cache_head_result = CacheHeadResult(
        status=CacheStatus.HIT,
        latest_cache_source_digest="some-digest",
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value.head.return_value = cache_head_result

    result = runner.invoke(
        qontract_cli.early_exit_cache, "head -i a -v b --dry-run -c {} -s shard-1"
    )
    cache_key = CacheKey(
        integration="a",
        integration_version="b",
        dry_run=True,
        cache_source={},
        shard="shard-1",
    )
    assert result.exit_code == 0
    assert (
        result.output
        == f"cache_source_digest: {cache_key.cache_source_digest}\n{cache_head_result}\n"
    )


def test_early_exit_cache_delete(
    env_vars: None, mock_queries: None, mock_early_exit_cache: Mock
) -> None:
    runner = CliRunner()

    result = runner.invoke(
        qontract_cli.early_exit_cache, "delete -i a -v b --dry-run -d abc -s shard-1"
    )

    assert result.exit_code == 0
    assert result.output == "deleted\n"


@pytest.fixture
def mock_aws_cost_report_command(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.AwsCostReportCommand", autospec=True)


def test_get_aws_cost_report(
    env_vars: None, mock_queries: None, mock_aws_cost_report_command: Mock
) -> None:
    mock_aws_cost_report_command.create.return_value.execute.return_value = (
        "some report"
    )
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        "aws-cost-report",
        obj={},
    )

    assert result.exit_code == 0
    assert result.output == "some report\n"
    mock_aws_cost_report_command.create.assert_called_once_with(thread_pool_size=5)
    mock_aws_cost_report_command.create.return_value.execute.assert_called_once_with()


@pytest.fixture
def mock_openshift_cost_report_command(mocker: MockerFixture) -> Mock:
    return mocker.patch("tools.qontract_cli.OpenShiftCostReportCommand", autospec=True)


def test_get_openshift_cost_report(
    env_vars: None, mock_queries: None, mock_openshift_cost_report_command: Mock
) -> None:
    mock_openshift_cost_report_command.create.return_value.execute.return_value = (
        "some report"
    )
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        "openshift-cost-report",
        obj={},
    )

    assert result.exit_code == 0
    assert result.output == "some report\n"
    mock_openshift_cost_report_command.create.assert_called_once_with(
        thread_pool_size=5
    )
    mock_openshift_cost_report_command.create.return_value.execute.assert_called_once_with()


@pytest.fixture
def mock_openshift_cost_optimization_report_command(mocker: MockerFixture) -> Mock:
    return mocker.patch(
        "tools.qontract_cli.OpenShiftCostOptimizationReportCommand", autospec=True
    )


def test_get_openshift_cost_optimization_report(
    env_vars: None,
    mock_queries: None,
    mock_openshift_cost_optimization_report_command: Mock,
) -> None:
    mock_openshift_cost_optimization_report_command.create.return_value.execute.return_value = "some report"
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        "openshift-cost-optimization-report",
        obj={},
    )

    assert result.exit_code == 0
    assert result.output == "some report\n"
    mock_openshift_cost_optimization_report_command.create.assert_called_once_with(
        thread_pool_size=5
    )
    mock_openshift_cost_optimization_report_command.create.return_value.execute.assert_called_once_with()


def test_external_resources_get_credentials(
    mock_get_app_interface_vault_settings: Mock,
    mock_create_secret_reader: Mock,
    mocker: MockerFixture,
) -> None:
    mocker.patch("tools.qontract_cli.gql")

    provisioner_account = Mock()
    state_account = Mock()
    mock_aws_accounts_query = mocker.patch("tools.qontract_cli.aws_accounts_query")
    mock_aws_accounts_query.side_effect = [
        Mock(accounts=[provisioner_account]),
        Mock(accounts=[state_account]),
    ]

    mock_get_settings = mocker.patch("tools.qontract_cli.get_er_settings")
    mock_get_settings.return_value.state_dynamodb_account.name = "state-account"

    mock_read_all = mock_create_secret_reader.return_value.read_all_secret
    mock_read_all.side_effect = [
        {"aws_access_key_id": "PROV_KEY", "aws_secret_access_key": "PROV_SECRET"},
        {"aws_access_key_id": "STATE_KEY", "aws_secret_access_key": "STATE_SECRET"},
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.external_resources,
        "--provisioner provisioner --provider elasticache --identifier i get-credentials",
        obj={},
    )

    assert result.exit_code == 0
    expected = (
        "[default]\n"
        "aws_access_key_id=PROV_KEY\n"
        "aws_secret_access_key=PROV_SECRET\n"
        "\n"
        "[external-resources-state]\n"
        "aws_access_key_id=STATE_KEY\n"
        "aws_secret_access_key=STATE_SECRET\n"
    )
    assert result.output == expected + "\n"


@pytest.fixture
def mock_cidr_deps(mocker: MockerFixture) -> Mock:
    mock_q = mocker.patch("tools.qontract_cli.queries", autospec=True)
    mocker.patch("reconcile.typed_queries.aws_vpcs.get_aws_vpcs", return_value=[])
    return mock_q


def test_cidr_blocks_for_cluster_next_block(mock_cidr_deps: Mock) -> None:
    mock_cidr_deps.get_clusters.return_value = [
        _make_cluster("c1", "10.0.0.0/24"),
        _make_cluster("c2", "10.0.1.0/24"),
    ]
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["cidr-blocks", "--for-cluster", "true", "--mask", "24"],
        obj={"options": {"output": "table"}},
    )
    assert result.exit_code == 0
    assert "10.0.2.0/24" in result.output


def test_cidr_blocks_within_finds_first_available(mock_cidr_deps: Mock) -> None:
    mock_cidr_deps.get_clusters.return_value = [
        _make_cluster("c1", "10.0.0.0/24"),
        _make_cluster("c2", "10.0.1.0/24"),
    ]
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        [
            "cidr-blocks",
            "--for-cluster",
            "true",
            "--mask",
            "24",
            "--within",
            "10.0.0.0/16",
        ],
        obj={"options": {"output": "table"}},
    )
    assert result.exit_code == 0
    assert "10.0.2.0/24" in result.output


def test_cidr_blocks_within_no_existing_clusters(mock_cidr_deps: Mock) -> None:
    mock_cidr_deps.get_clusters.return_value = [
        _make_cluster("c1", "10.0.0.0/24"),
    ]
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        [
            "cidr-blocks",
            "--for-cluster",
            "true",
            "--mask",
            "24",
            "--within",
            "172.16.0.0/16",
        ],
        obj={"options": {"output": "table"}},
    )
    assert result.exit_code == 0
    assert "172.16.0.0/24" in result.output


def test_cidr_blocks_within_exhausted(mock_cidr_deps: Mock) -> None:
    mock_cidr_deps.get_clusters.return_value = [
        _make_cluster("c1", "10.0.0.0/24"),
        _make_cluster("c2", "10.0.1.0/24"),
    ]
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        [
            "cidr-blocks",
            "--for-cluster",
            "true",
            "--mask",
            "24",
            "--within",
            "10.0.0.0/23",
        ],
        obj={"options": {"output": "table"}},
    )
    assert result.exit_code != 0
    assert "No available" in result.output


def test_cidr_blocks_within_invalid_cidr(mock_cidr_deps: Mock) -> None:
    mock_cidr_deps.get_clusters.return_value = []
    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["cidr-blocks", "--for-cluster", "true", "--within", "not-a-cidr"],
        obj={"options": {"output": "table"}},
    )
    assert result.exit_code != 0
    assert "Invalid CIDR" in result.output


@pytest.fixture
def mock_review_queue_gl(mocker: MockerFixture) -> Mock:
    mocker.patch(
        "tools.qontract_cli.queries.get_app_interface_settings",
        autospec=True,
        return_value={},
    )
    mocker.patch(
        "tools.qontract_cli.queries.get_gitlab_instance",
        autospec=True,
        return_value={},
    )
    mocker.patch("tools.qontract_cli.SecretReader", autospec=True)
    mocker.patch("tools.qontract_cli.init_jjb", autospec=True)
    mocker.patch("tools.qontract_cli.slackapi_from_queries", autospec=True)

    mock_gl = mocker.patch("tools.qontract_cli.GitLabApi", autospec=True)
    gl_instance = mock_gl.return_value
    gl_instance.get_app_sre_group_users.return_value = []
    gl_instance.is_assigned_by_team.return_value = False
    gl_instance.is_last_action_by_team.return_value = True

    mocker.patch(
        "tools.qontract_cli.queries.get_review_repos",
        autospec=True,
        return_value=[
            {
                "name": "app-interface",
                "url": "https://gitlab.example.com/service/app-interface",
            }
        ],
    )

    return gl_instance


def _mock_mr(iid: int, labels: list[str]) -> Mock:
    mr = Mock()
    mr.iid = iid
    mr.draft = False
    mr.title = f"MR {iid}"
    mr.web_url = f"https://gitlab.example.com/mr/{iid}"
    mr.updated_at = "2026-06-10T00:00:00Z"
    mr.merge_status = "can_be_merged"
    mr.author = {"username": "tenant-user"}
    mr.attributes = {"labels": labels}
    mr.commits.return_value = [Mock()]
    return mr


def test_review_queue_includes_approved_mr_with_pipeline_error(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(1, [LGTM, PIPELINE_ERROR])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.FAILED)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 1" in result.output


def test_review_queue_excludes_approved_mr_without_error(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [_mock_mr(2, [LGTM])]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.SUCCESS)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 2" not in result.output


def test_review_queue_excludes_pipeline_error_without_approval(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(3, [PIPELINE_ERROR])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.FAILED)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 3" not in result.output


def test_review_queue_excludes_bot_hold(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [_mock_mr(4, [HOLD])]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 4" not in result.output


def test_review_queue_includes_self_serviceable_mr_with_pipeline_error(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(4, [LGTM, PIPELINE_ERROR, SELF_SERVICEABLE])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.FAILED)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 4" in result.output


def test_review_queue_includes_saas_file_update_mr_with_pipeline_error(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(5, [LGTM, PIPELINE_ERROR, SAAS_FILE_UPDATE])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.FAILED)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 5" in result.output


def test_review_queue_excludes_self_serviceable_mr_without_error(
    mock_review_queue_gl: Mock,
) -> None:
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(6, [SELF_SERVICEABLE])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.SUCCESS)
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 6" not in result.output


def test_review_queue_includes_mr_when_skipped_pipeline_precedes_success(
    mock_review_queue_gl: Mock,
) -> None:
    """An MR whose most recent pipeline is 'skipped' (merge_request_event)
    but has a successful CI pipeline behind it must still appear in the
    review queue — the skipped pipeline is not a real CI result."""
    mock_review_queue_gl.get_merge_requests.return_value = [
        _mock_mr(8, ["not-self-serviceable"])
    ]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.SKIPPED),
        Mock(status=PipelineStatus.SUCCESS),
    ]
    mock_review_queue_gl.is_last_action_by_team.return_value = False

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 8" in result.output


def test_review_queue_includes_bot_authored_self_serviceable_mr_with_pipeline_error(
    mock_review_queue_gl: Mock,
) -> None:
    mr = _mock_mr(7, [LGTM, PIPELINE_ERROR, SELF_SERVICEABLE])
    mr.author = {"username": "app-sre-bot"}
    mock_review_queue_gl.get_merge_requests.return_value = [mr]
    mock_review_queue_gl.get_merge_request_pipelines.return_value = [
        Mock(status=PipelineStatus.FAILED)
    ]
    mock_review_queue_gl.get_app_sre_group_users.return_value = [
        Mock(username="app-sre-bot")
    ]

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["app-interface-review-queue"],
        obj={"options": {"output": "table", "sort": True}},
    )
    assert result.exit_code == 0
    assert "MR 7" in result.output


def test_rds_command_columns_replace_storage_type(mocker: MockerFixture) -> None:
    mocker.patch("tools.qontract_cli.tfr.get_namespaces", return_value=[])
    mocker.patch("tools.qontract_cli.queries.get_aws_accounts", return_value=[])
    mocker.patch("tools.qontract_cli.load_rds_eol_data", return_value=[])

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.get,
        ["rds"],
        obj={"options": {"output": "table", "sort": False}},
    )
    assert result.exit_code == 0
    output = result.output
    assert "STORAGE_TYPE" not in output
    assert "AUTO_MINOR_VERSION_UPGRADE" in output
    assert "EOL_DATE" in output
    assert "NEXT_VERSION" in output


def test_rds_attr_preserves_false_override() -> None:
    overrides: dict = {"auto_minor_version_upgrade": False}
    defaults: dict = {"auto_minor_version_upgrade": True}
    assert (
        qontract_cli.rds_attr("auto_minor_version_upgrade", overrides, defaults)
        is False
    )
    assert qontract_cli.rds_attr("auto_minor_version_upgrade", {}, defaults) is True
    assert qontract_cli.rds_attr("auto_minor_version_upgrade", {}, {}) is None


def test_rds_attr_falls_through_when_key_absent() -> None:
    overrides: dict = {}
    defaults: dict = {"engine": "postgres"}
    assert qontract_cli.rds_attr("engine", overrides, defaults) == "postgres"
    assert qontract_cli.rds_attr("engine", {"engine": "mysql"}, defaults) == "mysql"


@pytest.fixture
def mock_qontract_api_config(mocker: MockerFixture) -> Mock:
    return mocker.patch(
        "tools.qontract_cli.config.get_config",
        return_value={
            "qontract-api": {
                "server": "https://qontract-api.example.com",
                "token": "tok",
            }
        },
    )


@pytest.fixture
def mock_requests_session(mocker: MockerFixture) -> Mock:
    mock_session_cls = mocker.patch("tools.qontract_cli.requests.Session")
    return mock_session_cls.return_value.__enter__.return_value


def test_sso_client_create_success(
    mock_qontract_api_config: Mock, mock_requests_session: Mock
) -> None:
    mock_requests_session.post.return_value = Mock(
        json=Mock(
            return_value={
                "status_url": "https://internal-host/api/v1/integrations/sso-client/manual/task-123"
            }
        )
    )
    mock_requests_session.get.return_value = Mock(
        json=Mock(
            return_value={
                "status": "success",
                "vault_secret_path": "app-sre/creds/rhidp/manual/my-client",
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.sso_client,
        ["create", "my-client", "--redirect-uri", "https://example.org/login"],
    )

    assert result.exit_code == 0
    assert "app-sre/creds/rhidp/manual/my-client" in result.output

    post_kwargs = mock_requests_session.post.call_args.kwargs
    assert (
        mock_requests_session.post.call_args.args[0]
        == "https://qontract-api.example.com/api/v1/integrations/sso-client/manual"
    )
    assert post_kwargs["json"]["client_name"] == "my-client"
    assert post_kwargs["json"]["redirect_uris"] == ["https://example.org/login"]
    assert post_kwargs["json"]["keycloak_instance"] == {
        "url": qontract_cli.RHIDP_KEYCLOAK_INSTANCES["prod"]["url"],
        "secret": {
            "secret_manager_url": qontract_cli.RHIDP_KEYCLOAK_INSTANCES["prod"][
                "secret_manager_url"
            ],
            "path": qontract_cli.RHIDP_KEYCLOAK_INSTANCES["prod"]["path"],
        },
    }

    get_args, get_kwargs = mock_requests_session.get.call_args
    assert (
        get_args[0]
        == "https://qontract-api.example.com/api/v1/integrations/sso-client/manual/task-123"
    )
    assert get_kwargs["params"] == {"timeout": 60}


def test_sso_client_create_stage_environment(
    mock_qontract_api_config: Mock, mock_requests_session: Mock
) -> None:
    mock_requests_session.post.return_value = Mock(
        json=Mock(
            return_value={
                "status_url": "https://internal-host/api/v1/integrations/sso-client/manual/task-123"
            }
        )
    )
    mock_requests_session.get.return_value = Mock(
        json=Mock(
            return_value={
                "status": "success",
                "vault_secret_path": "app-sre/creds/rhidp/manual/my-client",
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.sso_client,
        [
            "create",
            "my-client",
            "--environment",
            "stage",
            "--redirect-uri",
            "https://example.org/login",
        ],
    )

    assert result.exit_code == 0
    post_kwargs = mock_requests_session.post.call_args.kwargs
    assert (
        post_kwargs["json"]["keycloak_instance"]["url"]
        == qontract_cli.RHIDP_KEYCLOAK_INSTANCES["stage"]["url"]
    )


def test_sso_client_create_task_failure_exits_nonzero(
    mock_qontract_api_config: Mock, mock_requests_session: Mock
) -> None:
    mock_requests_session.post.return_value = Mock(
        json=Mock(
            return_value={
                "status_url": "https://internal-host/api/v1/integrations/sso-client/manual/task-123"
            }
        )
    )
    mock_requests_session.get.return_value = Mock(
        json=Mock(
            return_value={
                "status": "failed",
                "errors": ["Keycloak unreachable"],
                "vault_secret_path": None,
            }
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.sso_client,
        ["create", "my-client", "--redirect-uri", "https://example.org/login"],
    )

    assert result.exit_code != 0
    assert "Keycloak unreachable" in result.output


def test_sso_client_create_requires_qontract_api_config(
    mocker: MockerFixture,
) -> None:
    mocker.patch("tools.qontract_cli.config.get_config", return_value={})

    runner = CliRunner()
    result = runner.invoke(
        qontract_cli.sso_client,
        ["create", "my-client", "--redirect-uri", "https://example.org/login"],
    )

    assert result.exit_code != 0
    assert "Missing [qontract-api]" in result.output
