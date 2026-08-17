"""Default User-Agent for qontract_utils HTTP clients.

Every HTTP-based Layer 1 API client sends this by default so external services
can attribute traffic to qontract-utils. Callers embedded in a larger service
(e.g. qontract-api) should pass their own app name/version instead so the
embedding service is what shows up in the traffic, not the shared library.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def resolve_version(package: str, fallback: str = "unknown") -> str:
    """Resolve the installed version of a package, falling back if not found.

    Shared by every module that builds a `<package>/<version>` User-Agent
    string, so the fallback behavior only needs to change in one place.
    """
    try:
        return version(package)
    except PackageNotFoundError:
        return fallback


DEFAULT_USER_AGENT = f"qontract-utils/{resolve_version('qontract-utils')}"
