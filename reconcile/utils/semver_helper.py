import semver


def make_semver(major, minor, patch):
    return str(semver.VersionInfo(major=major, minor=minor, patch=patch))


def sort_versions(versions):
    """sort versions by semver

    Args:
        versions (list): string versions to sort

    Returns:
        list: string versions sorted by semver
    """
    semver_versions = sorted([
        semver.VersionInfo(**semver.parse(v))
        for v in versions
    ])
    return [str(v) for v in semver_versions]
