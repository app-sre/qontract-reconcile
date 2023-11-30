import pytest
import semver

import reconcile.utils.semver_helper as svh


def test_sort_versions():
    versions = ["4.8.0", "4.8.0-rc.0", "4.8.0-fc.1", "4.8.1", "4.8.0-rc.2"]
    expected = ["4.8.0-fc.1", "4.8.0-rc.0", "4.8.0-rc.2", "4.8.0", "4.8.1"]
    assert expected == svh.sort_versions(versions)


def test_is_version_bumped_lower():
    assert svh.is_version_bumped("0.5.0", "0.6.0") is False


def test_is_version_bumped_higher():
    assert svh.is_version_bumped("0.5.0", "0.4.0") is True


def test_is_version_bumped_equal():
    assert svh.is_version_bumped("0.5.0", "0.5.0") is False


@pytest.mark.parametrize(
    "version_str, expected, optional_minor_and_patch",
    [
        ("0.4.0", semver.VersionInfo(major=0, minor=4, patch=0), False),
        (
            "0.4.0-6+gaaaaaaa",
            semver.VersionInfo(
                major=0, minor=4, patch=0, prerelease="6", build="gaaaaaaa"
            ),
            False,
        ),
        ("15", semver.VersionInfo(major=15, minor=0, patch=0), True),
        ("15.0", semver.VersionInfo(major=15, minor=0, patch=0), True),
        # no minor and patch
        pytest.param(
            "15",
            None,
            False,
            marks=pytest.mark.xfail(raises=ValueError, strict=True),
        ),
        pytest.param(
            "15.0",
            None,
            False,
            marks=pytest.mark.xfail(raises=ValueError, strict=True),
        ),
    ],
)
def test_parse_semver(
    version_str: str, optional_minor_and_patch: bool, expected: semver.VersionInfo
) -> None:
    assert svh.parse_semver(version_str, optional_minor_and_patch) == expected


def test_comparison_with_optional_minor_and_patch() -> None:
    assert svh.parse_semver("13.0", optional_minor_and_patch=True) < svh.parse_semver(
        "13.1", optional_minor_and_patch=True
    )
