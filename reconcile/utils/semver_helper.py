import semver


def make_semver(major, minor, patch):
    return str(semver.VersionInfo.parse(major=major, minor=minor, patch=patch))
