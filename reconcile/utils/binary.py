import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from functools import wraps
from typing import Any


def binary(binaries: Iterable[str] | None = None) -> Callable:
    """Check that a binary exists before execution."""
    if binaries is None:
        binaries = []

    def deco_binary(f: Callable) -> Callable:
        @wraps(f)
        def f_binary(*args: Any, **kwargs: Any) -> None:
            for b in binaries:
                if not shutil.which(b):
                    raise Exception(
                        f"Aborting: Could not find binary: {b}. "
                        + f"Hint: https://command-not-found.com/{b}"
                    )
            f(*args, **kwargs)

        return f_binary

    return deco_binary


def binary_version(
    binary: str,
    version_args: Iterable[str],
    search_regex: str,
    expected_versions: Iterable[str],
) -> Callable:
    """Check that a binary exists and is a desired version"""

    def deco_binary_version(f: Callable) -> Callable:
        @wraps(f)
        def f_binary_version(*args: Any, **kwargs: Any) -> None:
            regex = re.compile(search_regex)

            cmd = [binary]
            cmd.extend(version_args)
            try:
                result = subprocess.run(cmd, capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                msg = (
                    f"Could not execute binary '{binary}' for binary version check: {e}"
                )
                raise Exception(msg) from e

            found = False
            match = None
            for line in result.stdout.splitlines():
                match = regex.search(line.decode("utf-8"))
                if match is not None:
                    found = True
                    break

            if not found or not match:
                raise Exception(
                    f"Could not find version for binary '{binary}' via regex "
                    f"for binary version check: "
                    f"regex did not match: '{search_regex}'"
                )

            version = match.group(1)
            if version not in expected_versions:
                raise Exception(
                    f"Binary version check for binary {binary} failed! "
                    f"Expected: {expected_versions}, found: {version}"
                )

            f(*args, **kwargs)

        return f_binary_version

    return deco_binary_version
