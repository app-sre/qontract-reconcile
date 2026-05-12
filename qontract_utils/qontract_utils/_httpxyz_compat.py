"""httpxyz forward-compatibility module (ADR-020).

httpxyz registers itself as sys.modules["httpx"] on import, so any library
doing ``import httpx`` transparently gets httpxyz.  This module is imported
from ``qontract_utils.__init__`` to ensure httpxyz is loaded before any
transitive dependency can pull in the real httpx.
"""

import sys

import httpxyz

_httpx = sys.modules.get("httpx")
if _httpx is not httpxyz:
    msg = (
        "httpxyz must be imported before any library that uses httpx. "
        f"sys.modules['httpx'] is {_httpx!r}, expected httpxyz. "
        "See ADR-020."
    )
    raise RuntimeError(msg)

del _httpx
