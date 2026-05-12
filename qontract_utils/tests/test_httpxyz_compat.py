"""Tests for the httpxyz forward-compatibility module (ADR-020).

Uses subprocess isolation so each test gets a clean sys.modules state.
"""

import subprocess
import sys
from collections.abc import Callable
from textwrap import dedent

import pytest


@pytest.fixture
def run_subprocess() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """Run a Python code snippet in an isolated subprocess."""

    def _run(code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-W", "default", "-c", dedent(code)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    return _run


@pytest.mark.parametrize(
    ("code", "test_id"),
    [
        pytest.param(
            """
            import qontract_utils  # noqa: F401
            import sys
            import httpxyz
            httpx = sys.modules["httpx"]
            assert httpx is httpxyz, f"expected httpx -> httpxyz, got {httpx}"
            print("OK")
            """,
            "qontract_utils_registers_httpxyz",
            id="qontract_utils_registers_httpxyz",
        ),
        pytest.param(
            """
            import httpxyz  # noqa: F401
            import qontract_utils  # noqa: F401
            print("OK")
            """,
            "httpxyz_first_then_qontract_utils",
            id="httpxyz_first_then_qontract_utils",
        ),
        pytest.param(
            """
            import qontract_utils  # noqa: F401
            import httpx
            import httpxyz
            assert httpx is httpxyz, f"httpx is {httpx}, not httpxyz"
            print("OK")
            """,
            "transitive_httpx_import_gets_httpxyz",
            id="transitive_httpx_import_gets_httpxyz",
        ),
    ],
)
def test_httpxyz_compat_registration(
    run_subprocess: Callable[[str], subprocess.CompletedProcess[str]],
    code: str,
    test_id: str,
) -> None:
    """Verify httpxyz is registered as httpx in sys.modules."""
    result = run_subprocess(code)
    assert result.returncode == 0, f"[{test_id}] {result.stderr}"
    assert "OK" in result.stdout


@pytest.mark.skipif(
    subprocess.run(  # noqa: S603, PLW1510
        [sys.executable, "-c", "import httpx"],
        capture_output=True,
    ).returncode
    != 0,
    reason="real httpx not installed (expected in this project)",
)
def test_real_httpx_before_qontract_utils_raises(
    run_subprocess: Callable[[str], subprocess.CompletedProcess[str]],
) -> None:
    """Loading real httpx before qontract_utils raises RuntimeError."""
    result = run_subprocess("""
        import httpx  # noqa: F401
        import qontract_utils  # noqa: F401
    """)
    assert result.returncode != 0
    assert "httpxyz must be imported before" in result.stderr
