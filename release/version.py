#!/usr/bin/env python3

import os
import re
import subprocess
import sys
from subprocess import PIPE
from typing import Optional

GIT_VERSION_FILE = "GIT_VERSION"


def git() -> str:
    """get the version from git. Can be
    - X.Y.Z if a tag is set on the current HEAD
    - X.Y.Z-<count>-g<commitid> otherwise where
        - X.Y.Z is the latest version tag found
        - <count> is the number of commits since then
        - <commitid> is the current HEAD commitid
    """
    cmd = "git describe --tags --match=[0-9]*.[0-9]*.[0-9]*"
    try:
        p = subprocess.run(cmd.split(" "), stdout=PIPE, stderr=PIPE, check=True)
        v = p.stdout.decode("utf-8").strip()
        # tox is running setup.py sdist from the git repo, and then runs again outside
        # of the git repo. At this second step, we cannot run git commands.
        # So we save the git version in a file and include it in the source distribution
        with open(GIT_VERSION_FILE, "w") as f:
            f.write(v)
        return v
    except subprocess.CalledProcessError as e:
        # if we're not in a git repo, try reading out from the GIT_VERSION file
        if os.path.exists(GIT_VERSION_FILE):
            with open(GIT_VERSION_FILE, "r") as f:
                return f.read()
        print(e.stderr)
        raise e


def commit(length: int = 7) -> str:
    """get the current git commitid"""
    cmd = f"git rev-parse --short={length} HEAD"
    p = subprocess.run(cmd.split(" "), stdout=PIPE, stderr=PIPE, check=True)
    return p.stdout.decode("utf-8").strip()


def semver(git_version: Optional[str] = None) -> str:
    """get a semantic version out of the input git version (see git())
    - if a X.Y.Z tag is set on the current HEAD, we'll use this
    - else we'll use X.Y.<Z+1>-<count>+<commitid> to respect semver and version
      ordering. <count> is the prerelease id, <commitid> is a buildinfo
    """
    v = git_version or git()
    m = re.match(r"(\d+)\.(\d+)\.(\d+)-(\d+)-g(.+)", v)
    if m:
        major, minor, patch, prerelease, buildinfo = m.groups()
        # semver prerelase are supposed to show build increments *prior* to a release.
        # So we're bumping the patch number to show what the next release would be.
        # this allows correct version ordering
        patch = str(int(patch) + 1)
        # X.Y.Z-<count>-g<commitid> is not a valid as <count>-g<commitid> would be
        # compared as a string, leading to (count=50) < (count=6)
        # X.Y.Z-<count>+<commitid> is valid .
        #   <count> is then the prerelease field, treated as a numeric.
        #   <commitid> is then a buildinfo string, not used in version comparisons
        v = f"{major}.{minor}.{patch}-{prerelease}+{buildinfo}"
    return str(v)


def pip(git_version: Optional[str] = None) -> str:
    """get a pip version out of the input git version (see git()),
    according to https://peps.python.org/pep-0440/
    - if a X.Y.Z tag is set on the current HEAD, we'll use this
    - else we'll use X.Y.(Z+1).pre<count>+<commitid> to respect PEP-0440 versioning
    """
    return semver(git_version).replace("-", ".pre").split("+", maxsplit=1)[0]
    # Alternatively, use postreleases
    # v = git_version or git()
    # m = re.match(r"(\d+)\.(\d+)\.(\d+)-(\d+)-g(.+)", v)
    # if m:
    #     major, minor, patch, count, commitid = m.groups()
    #     v = f"{major}.{minor}.{patch}.post{count}+{commitid}"
    # return str(v)


def docker(git_version: Optional[str] = None) -> str:
    # docker tags don't like '+' characters, let's remove the buildinfo/commitid
    return pip(git_version)


if __name__ == "__main__":
    type_param = sys.argv[1] if len(sys.argv) > 1 else "--git"
    v = {
        "--git": git(),
        "--commit": commit(),
        "--semver": semver(),
        "--pip": pip(),
        "--docker": docker(),
    }[type_param]
    print(v)
