from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def fx() -> Callable:
    def _fx(name: str) -> str:
        return (Path(__file__).parent / "fixtures" / name).read_text()

    return _fx


COST_MANAGEMENT_CONSOLE_BASE_URL = (
    "https://console.redhat.com/openshift/cost-management"
)

COST_REPORT_SECRET = {
    "api_base_url": "base_url",
    "token_url": "token_url",
    "client_id": "client_id",
    "client_secret": "client_secret",
    "scope": "scope",
    "console_base_url": COST_MANAGEMENT_CONSOLE_BASE_URL,
}
