from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def fx() -> Callable:
    def _fx(name: str) -> str:
        return (Path(__file__).parent / "fixtures" / name).read_text()

    return _fx
