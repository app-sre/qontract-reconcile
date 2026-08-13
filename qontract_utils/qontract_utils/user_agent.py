"""Default User-Agent for qontract_utils HTTP clients.

Every HTTP-based Layer 1 API client sends this by default so external services
can attribute traffic to qontract-utils. Callers embedded in a larger service
(e.g. qontract-api) should pass their own app name/version instead so the
embedding service is what shows up in the traffic, not the shared library.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    _QONTRACT_UTILS_VERSION = version("qontract-utils")
except PackageNotFoundError:
    _QONTRACT_UTILS_VERSION = "unknown"

DEFAULT_USER_AGENT = f"qontract-utils/{_QONTRACT_UTILS_VERSION}"
