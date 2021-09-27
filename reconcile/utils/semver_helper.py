import semver
from typing import List, Iterable

def make_semver(major: int, minor: int, patch: int) -> str:
    return str(semver.VersionInfo(major=major, minor=minor, patch=patch))


def parse_semver(version: str) -> semver.VersionInfo:
    return semver.VersionInfo.parse(version)


def sort_versions(versions: Iterable[str]) -> List[str]:
    """sort versions by semver

    Args:
        versions (list): string versions to sort

    Returns:
        list: string versions sorted by semver
    """
    semver_versions = sorted([parse_semver(v) for v in versions])
    return [str(v) for v in semver_versions]
