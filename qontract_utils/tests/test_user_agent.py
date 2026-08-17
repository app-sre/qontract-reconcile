"""Tests for qontract_utils.user_agent."""

from importlib.metadata import PackageNotFoundError

import pytest
from pytest_mock import MockerFixture
from qontract_utils.user_agent import DEFAULT_USER_AGENT, resolve_version


def test_resolve_version_returns_installed_version(mocker: MockerFixture) -> None:
    mocker.patch("qontract_utils.user_agent.version", return_value="1.2.3")
    assert resolve_version("some-package") == "1.2.3"


def test_resolve_version_falls_back_when_package_not_found(
    mocker: MockerFixture,
) -> None:
    mocker.patch("qontract_utils.user_agent.version", side_effect=PackageNotFoundError)
    assert resolve_version("some-package") == "unknown"


def test_resolve_version_uses_custom_fallback(mocker: MockerFixture) -> None:
    mocker.patch("qontract_utils.user_agent.version", side_effect=PackageNotFoundError)
    assert resolve_version("some-package", fallback="dev") == "dev"


@pytest.mark.parametrize("prefix", ["qontract-utils/"])
def test_default_user_agent_has_qontract_utils_prefix(prefix: str) -> None:
    assert DEFAULT_USER_AGENT.startswith(prefix)
