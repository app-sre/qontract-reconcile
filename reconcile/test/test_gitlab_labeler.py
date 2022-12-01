from typing import (
    Any,
    Optional,
)
from unittest.mock import (
    create_autospec,
    patch,
)

import reconcile.gitlab_labeler as gl
from reconcile.queries import APPS_QUERY
from reconcile.utils import gql

from .fixtures import Fixtures


class TestData:
    """Class to add data to tests in setUp. It will be used by mocks"""

    def __init__(self):
        self._apps = []

    @property
    def apps(self) -> list[dict]:
        return self._apps

    @apps.setter
    def apps(self, apps: list[dict]) -> None:
        if not isinstance(apps, list):
            raise TypeError(f"Expecting list, have {type(apps)}")
        self._apps = apps


# This was originally written in unittest, hence the use of xunit-style
# setup/teardown methods instead of pytest fixtures.
class TestOnboardingGuesser:
    def setup_method(self) -> None:
        self.test_data = TestData()

        self.fxt = Fixtures("apps")
        self.app1 = self.fxt.get_json("app1.json")
        self.app2 = self.fxt.get_json("app2.json")
        self.app3 = self.fxt.get_json("childapp.json")
        self.app4 = self.fxt.get_json("parentapp.json")

        # Patcher for GqlApi methods
        self.gql_patcher = patch.object(gql, "get_api", autospec=True)
        self.gql = self.gql_patcher.start()
        gqlapi_mock = create_autospec(gql.GqlApi)
        self.gql.return_value = gqlapi_mock
        gqlapi_mock.query.side_effect = self.mock_gql_query

    def mock_gql_query(self, query: str) -> Optional[dict[str, Any]]:
        """Mock for GqlApi.query using test_data set in setUp"""
        if query == APPS_QUERY:
            return {"apps": self.test_data.apps}
        else:
            return None

    def teardown_method(self) -> None:
        """cleanup patches created in self.setUp"""
        self.gql_patcher.stop()

    def test_get_app_list(self):
        self.test_data.apps = [self.app1]
        t = gl.get_app_list()
        assert t == {"normalapp": {"onboardingStatus": "BestEffort", "parentApp": None}}

    def test_get_app_list_2(self):
        self.test_data.apps = [self.app1, self.app2]
        t = gl.get_app_list()
        assert t, {
            "normalapp": {"onboardingStatus": "BestEffort", "parentApp": None},
            "normalapp2": {"onboardingStatus": "BestEffort", "parentApp": None},
        }

    def test_get_parents_list(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        t = gl.get_parents_list()
        assert t == {"parentapp"}

    def test_get_parents_list_empty(self):
        self.test_data.apps = [self.app1, self.app2]
        t = gl.get_parents_list()
        assert t == set()

    def test_guess_onboarding_status_child(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ["data/services/parentapp/childapp"]

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        assert t == "BestEffort"

    def test_guess_onboarding_status_parent(self):
        self.test_data.apps = [self.app1, self.app2, self.app3, self.app4]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ["data/services/parentapp/test"]

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        assert t == "OnBoarded"

    def test_guess_onboarding_status_normal(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ["data/services/normalapp2"]

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        assert t == "BestEffort"

    def test_guess_onboarding_status_no_app(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ["data/test/test"]

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        assert t is None

    def test_guess_onboarding_status_key_error(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ["data/services/normalapp3"]

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        assert t is None
