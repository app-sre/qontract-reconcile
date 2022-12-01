import json
import os

import anymarkup


class Fixtures:
    def __init__(self, base_path):
        self.base_path = base_path

    def path(self, fixture):
        return os.path.join(
            os.path.dirname(__file__), "fixtures", self.base_path, fixture
        )

    def get(self, fixture):
        with open(self.path(fixture), "r") as f:
            return f.read().strip()

    def get_anymarkup(self, fixture):
        return anymarkup.parse(self.get(fixture), force_types=None)

    def get_json(self, fixture):
        return json.loads(self.get(fixture))
