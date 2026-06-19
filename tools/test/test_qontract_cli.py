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
from typing import TYPE_CHECKING

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
