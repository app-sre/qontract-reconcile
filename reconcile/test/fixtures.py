import json
import os
from typing import Any

import anymarkup


class Fixtures:
    def __init__(self, base_path: str):
        self.base_path = base_path

    def path(self, fixture: str) -> str:
        return os.path.join(
            os.path.dirname(__file__), "fixtures", self.base_path, fixture
        )

    def get(self, fixture: str) -> str:
        with open(self.path(fixture), encoding="locale") as f:
            return f.read().strip()

    def get_anymarkup(self, fixture: str) -> Any:
        return anymarkup.parse(self.get(fixture), force_types=None)

    def get_json(self, fixture: str) -> Any:
        return json.loads(self.get(fixture))
