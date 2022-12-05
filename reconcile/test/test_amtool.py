import pytest
import semver

from reconcile.test.fixtures import Fixtures
from reconcile.utils import amtool


def test_minimal_version() -> None:
    if result := amtool.version():
        assert semver.VersionInfo.parse(str(result)).compare("0.24.0") >= 0
    else:
        pytest.fail(f"Error getting amtool version {result}")


def test_check_good_config() -> None:
    am_config = Fixtures("amtool").get("alertmanager.yaml")
    result = amtool.check_config(am_config)
    assert result


def test_check_bad_config() -> None:
    am_config = "bad: config"
    result = amtool.check_config(am_config)
    assert not result


def test_config_routes_test() -> None:
    am_config = Fixtures("amtool").get("alertmanager.yaml")
    labels = {"service": "foo1"}
    result = amtool.config_routes_test(am_config, labels)
    assert result
    assert str(result) == "team-X-mails"

    labels["severity"] = "critical"
    result = amtool.config_routes_test(am_config, labels)
    assert result
    assert str(result) == "team-X-pager"
