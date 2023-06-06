import packaging.version as pep440

from reconcile.utils.semver_helper import parse_semver
from release import version


def test_version_semver() -> None:
    assert version.semver("0.4.0") == "0.4.0"
    assert version.semver("0.4.0-6-gaaaaaaa") == "0.4.1-6+aaaaaaa"


def test_semver_ordering() -> None:
    # 6 commits after 0.4.0
    assert parse_semver("0.4.1-6+aaaaaaa") > parse_semver("0.4.0")
    # prerelease version are lower than release ones
    assert parse_semver("0.4.0") > parse_semver("0.4.0-6+aaaaaaa")
    # build info (after '+') don't count in semver comparisons
    assert parse_semver("0.4.0-6+bbbbbbb") == parse_semver("0.4.0-6+aaaaaa")
    # 7 commits after 0.4.0 is a higher version than 6 commits after 0.4.0
    assert parse_semver("0.4.1-7+aaaaaaa") > parse_semver("0.4.1-6+aaaaaaa")
    # number of commits (prerelease) is treated as a number, not as a string: 50 > 6
    assert parse_semver("0.4.1-50+aaaaaaa") > parse_semver("0.4.1-6+aaaaaaa")


def test_version_pip() -> None:
    assert version.pip("0.4.0") == "0.4.0"
    assert version.pip("0.4.0-6-gaaaaaaa") == "0.4.1.pre6"
    # assert version.pip("0.4.0-6-gaaaaaaa") == "0.4.0.post6"


def test_pep440_ordering() -> None:
    assert pep440.Version("0.4.1") > pep440.Version("0.4.0")

    # using pre-releases
    assert pep440.Version("0.4.1.pre6") > pep440.Version("0.4.0")
    assert pep440.Version("0.4.1.pre6") < pep440.Version("0.4.1")
    assert pep440.Version("0.4.1.pre6") > pep440.Version("0.4.1.pre5")
    assert pep440.Version("0.4.1.pre50") > pep440.Version("0.4.1.pre6")

    # using post-releases
    assert pep440.Version("0.4.0.post6") > pep440.Version("0.4.0")
    assert pep440.Version("0.4.0.post6") < pep440.Version("0.4.1")
    assert pep440.Version("0.4.0.post6") > pep440.Version("0.4.0.post5")
    assert pep440.Version("0.4.0.post50") > pep440.Version("0.4.0.post6")


def test_version_docker() -> None:
    assert version.docker("0.4.0") == "0.4.0"
    assert version.docker("0.4.0-6-gaaaaaaa") == "0.4.1.pre6"
    # assert version.docker("0.4.0-6-gaaaaaaa") == "0.4.0.post6"
