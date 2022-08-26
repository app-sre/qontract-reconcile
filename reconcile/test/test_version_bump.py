import os
import requests
import pkg_resources
import pytest

import packaging.version as pep440


@pytest.mark.skipif(
    os.getuid() != 0,
    reason="This test is only for CI environments",
)
def test_version_bump():
    current_version = pkg_resources.get_distribution("qontract-reconcile").version
    pypi_version = requests.get(
        "https://pypi.org/pypi/qontract-reconcile/json", timeout=60
    ).json()["info"]["version"]
    assert pep440.Version(current_version) > pep440.Version(pypi_version)
