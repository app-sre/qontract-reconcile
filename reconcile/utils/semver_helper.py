from collections.abc import Iterable

import semver


def make_semver(major: int, minor: int, patch: int) -> str:
    return str(semver.VersionInfo(major=major, minor=minor, patch=patch))


def parse_semver(version: str) -> semver.VersionInfo:
    return semver.VersionInfo.parse(version)


def sort_versions(versions: Iterable[str]) -> list[str]:
    """sort versions by semver

    Args:
        versions (list): string versions to sort

    Returns:
        list: string versions sorted by semver
    """
    semver_versions = sorted([parse_semver(v) for v in versions])
    return [str(v) for v in semver_versions]


def is_version_bumped(current_version: str, previous_version: str) -> bool:
    return parse_semver(current_version) > parse_semver(previous_version)
