import pytest
from click.testing import CliRunner

from reconcile.utils.early_exit_cache import CacheStatus
from tools import qontract_cli


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", "some-bucket")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", "some-account")


@pytest.fixture
def mock_queries(mocker):
    mocker.patch("tools.qontract_cli.queries", autospec=True)


@pytest.fixture
def mock_state(mocker):
    return mocker.patch("tools.qontract_cli.init_state", autospec=True)


@pytest.fixture
def mock_early_exit_cache(mocker):
    return mocker.patch("tools.qontract_cli.EarlyExitCache", autospec=True)


def test_state_ls_with_integration(env_vars, mock_queries, mock_state):
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


def test_state_ls_without_integration(env_vars, mock_queries, mock_state):
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


def test_early_exit_cache_get(env_vars, mock_queries, mock_early_exit_cache):
    runner = CliRunner()
    mock_early_exit_cache.build.return_value.__enter__.return_value.get.return_value = (
        "some value"
    )

    result = runner.invoke(
        qontract_cli.early_exit_cache, "get -i a -v b --dry-run -c {}"
    )
    assert result.exit_code == 0
    assert result.output == "some value\n"


def test_early_exit_cache_set(env_vars, mock_queries, mock_early_exit_cache):
    runner = CliRunner()

    result = runner.invoke(
        qontract_cli.early_exit_cache,
        "set -i a -v b --no-dry-run -c {} -p {} -l log -t 30",
    )
    assert result.exit_code == 0
    mock_early_exit_cache.build.return_value.__enter__.return_value.set.assert_called()


def test_early_exit_cache_head(env_vars, mock_queries, mock_early_exit_cache):
    runner = CliRunner()

    mock_early_exit_cache.build.return_value.__enter__.return_value.head.return_value = CacheStatus.HIT

    result = runner.invoke(
        qontract_cli.early_exit_cache, "head -i a -v b --dry-run -c {}"
    )
    assert result.exit_code == 0
    assert result.output == f"{CacheStatus.HIT}\n"
