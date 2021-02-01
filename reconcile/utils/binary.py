import re

from functools import wraps
from distutils.spawn import find_executable
from subprocess import run, PIPE


def binary(binaries=[]):
    """Check that a binary exists before execution."""
    def deco_binary(f):
        @wraps(f)
        def f_binary(*args, **kwargs):
            for b in binaries:
                if not find_executable(b):
                    raise Exception(
                        "Aborting: Could not find binary: {}".format(b))
            f(*args, **kwargs)
        return f_binary
    return deco_binary


def binary_version(binary, version_args, search_regex, expected_version):
    """Check that a binary exists and is a desired version"""
    def deco_binary_version(f):
        @wraps(f)
        def f_binary_version(*args, **kwargs):
            regex = re.compile(search_regex)

            cmd = [binary]
            cmd.extend(version_args)
            res = run(cmd, stdout=PIPE, stderr=PIPE)
            if res.returncode != 0:
                raise Exception(
                    f"Could not execute binary '{binary}' for binary version "
                    f"check: return code {res.returncode}")

            found = False
            match = None
            for line in res.stdout.splitlines():
                match = regex.search(line.decode("utf-8"))
                if match is not None:
                    found = True
                    break

            if not found:
                raise Exception(
                    f"Could not find version for binary '{binary}' via regex "
                    f"for binary version check: "
                    f"regex did not match: '{search_regex}'")

            version = match.group(1)
            if version != expected_version:
                raise Exception(
                    f"Binary version check for binary {binary} failed! "
                    f"Expected: {expected_version}, found: {version}")

            f(*args, **kwargs)
        return f_binary_version
    return deco_binary_version
