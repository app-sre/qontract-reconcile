from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
    )


@pytest.fixture
def file_contents() -> Callable[[str], tuple[str, str]]:
    def contents(case: str) -> tuple[str, str]:
        path = os.path.join(
            os.path.dirname(__file__),
            "files",
        )

        with open(f"{path}/{case}.yml", encoding="locale") as f:
            a = f.read().strip()

        with open(f"{path}/{case}.result.yml", encoding="locale") as f:
            b = f.read().strip()

        return (a, b)

    return contents
