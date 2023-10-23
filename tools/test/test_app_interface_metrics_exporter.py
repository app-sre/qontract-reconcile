from click.testing import CliRunner
from pytest_mock import MockerFixture

from tools.app_interface_metrics_exporter import main, OverviewClustersGauge


def test_app_interface_metrics_exporter_main(
    mocker: MockerFixture,
) -> None:
    mocked_metrics = mocker.patch("tools.app_interface_metrics_exporter.metrics")
    mocker.patch(
        "tools.app_interface_metrics_exporter.get_clusters",
        return_value=[],
    )
    mocked_init_env = mocker.patch("tools.app_interface_metrics_exporter.init_env")

    result = CliRunner().invoke(
        main, ["--config", "config.toml", "--log-level", "DEBUG"]
    )

    assert result.exit_code == 0
    mocked_metrics.set_gauge.assert_called_once_with(
        OverviewClustersGauge(
            integration="app-interface-metrics-exporter",
        ),
        0,
    )
    mocked_init_env.assert_called_once_with(
        config_file="config.toml",
        log_level="DEBUG",
    )
