from collections import Counter

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from tools.app_interface_metrics_exporter import (
    OverviewOnboardingStatus,
    main,
)


@pytest.fixture
def onboarding_status() -> Counter:
    return Counter({
        "OnBoarded": 2,
    })


@pytest.fixture
def repo_inventory() -> Counter:
    return Counter({
        "app-sre",
        5,
    })


def test_app_interface_metrics_exporter_main(
    mocker: MockerFixture,
    onboarding_status: Counter,
    repo_inventory: Counter,
) -> None:
    mocked_metrics = mocker.patch("tools.app_interface_metrics_exporter.metrics")
    mocked_init_env = mocker.patch("tools.app_interface_metrics_exporter.init_env")
    mocker.patch("tools.app_interface_metrics_exporter.gql")
    mocker.patch(
        "tools.app_interface_metrics_exporter.get_onboarding_status",
        return_value=onboarding_status,
    )
    mocker.patch(
        "tools.app_interface_metrics_exporter.get_tf_repo_inventory",
        return_value=repo_inventory,
    )

    result = CliRunner().invoke(
        main,
        ["--config", "config.toml", "--log-level", "DEBUG"],
    )

    assert result.exit_code == 0
    mocked_metrics.set_gauge.assert_called_with(
        OverviewOnboardingStatus(
            integration="app-interface-metrics-exporter",
            status="OnBoarded",
        ),
        2,
    )
    mocked_init_env.assert_called_with(
        config_file="config.toml",
        log_level="DEBUG",
    )
