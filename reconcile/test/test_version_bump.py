import os
import requests
import pkg_resources
import pytest

from reconcile.utils.semver_helper import is_version_bumped


@pytest.mark.skipif(
    os.getuid() != 0,
    reason="This test is only for CI environments",
)
def test_version_bump():
    current_version = pkg_resources.get_distribution("qontract-reconcile").version
    pypi_version = requests.get("https://pypi.org/pypi/qontract-reconcile/json").json()[
        "info"
    ]["version"]
    assert (
        is_version_bumped(current_version, pypi_version) is True
    ), "setup.py version must be bumped. see README.md#release for details"
