"""Tests for the httpxyz forward-compatibility module (ADR-020).

Uses subprocess isolation so each test gets a clean sys.modules state.
"""

import subprocess
import sys
from textwrap import dedent

import pytest


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-W", "default", "-c", dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_import_registers_httpxyz_as_httpx() -> None:
    """Importing qontract_utils makes `import httpx` resolve to httpxyz."""
    result = _run("""
        import qontract_utils  # noqa: F401
        import sys
        import httpxyz
        httpx = sys.modules["httpx"]
        assert httpx is httpxyz, f"expected httpx -> httpxyz, got {httpx}"
        print("OK")
    """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_httpxyz_first_then_qontract_utils() -> None:
    """Importing httpxyz before qontract_utils works without error."""
    result = _run("""
        import httpxyz  # noqa: F401
        import qontract_utils  # noqa: F401
        print("OK")
    """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_transitive_httpx_import_gets_httpxyz() -> None:
    """After qontract_utils init, `import httpx` returns httpxyz."""
    result = _run("""
        import qontract_utils  # noqa: F401
        import httpx
        import httpxyz
        assert httpx is httpxyz, f"httpx is {httpx}, not httpxyz"
        print("OK")
    """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@pytest.mark.skipif(
    subprocess.run(  # noqa: S603, PLW1510
        [sys.executable, "-c", "import httpx"],
        capture_output=True,
    ).returncode
    != 0,
    reason="real httpx not installed (expected in this project)",
)
def test_real_httpx_before_qontract_utils_raises() -> None:
    """Loading real httpx before qontract_utils raises RuntimeError."""
    result = _run("""
        import httpx  # noqa: F401
        import qontract_utils  # noqa: F401
    """)
    assert result.returncode != 0
    assert "httpxyz must be imported before" in result.stderr
