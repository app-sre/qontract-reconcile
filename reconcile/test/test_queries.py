from typing import Any
from unittest.mock import create_autospec, patch
from copy import deepcopy

from reconcile import queries
from reconcile.utils import gql

from .fixtures import Fixtures


class TestQueries:
    def setup_method(self) -> None:
        """This starts a patch on gql.query method which will answer with the
        contents of self.fixture_data."""

        # Resetting this to make sure it is set from every test
        self.fixture_data: dict[str, Any] = {}

        self.gql_patcher = patch.object(gql, "get_api", autospec=True)
        self.gql = self.gql_patcher.start()
        gqlapi_mock = create_autospec(gql.GqlApi)
        self.gql.return_value = gqlapi_mock
        gqlapi_mock.query.side_effect = self.mock_gql_query

    def teardown_method(self) -> None:
        """Cleanup patches created in self.setup_method"""
        self.gql_patcher.stop()

    def mock_gql_query(self, query: str) -> dict[str, Any]:
        return self.fixture_data

    def test_get_permissions_return_all_slack_usergroup(self) -> None:
        self.fixture_data = Fixtures("slack_usergroups").get_anymarkup(
            "permissions.yml"
        )
        result = queries.get_permissions_for_slack_usergroup()
        assert {x["service"] for x in result} == {"slack-usergroup"}

    def test_get_pipelines_providers_all_defaults(self) -> None:
        data = Fixtures("queries").get_json("pipelines_providers_all_defaults.json")
        self.fixture_data = deepcopy(data)
        pps = queries.get_pipelines_providers()

        for k in ["retention", "taskTemplates", "pipelineTemplates", "deployResources"]:
            assert data["pipelines_providers"][0]["defaults"][k] == pps[0][k]

    def test_get_pipelines_providers_mixed(self) -> None:
        data = Fixtures("queries").get_json("pipelines_providers_mixed.json")
        self.fixture_data = deepcopy(data)
        pps = queries.get_pipelines_providers()

        # the fixture has some keys overriden from the defaults
        for k in ["taskTemplates", "pipelineTemplates"]:
            assert data["pipelines_providers"][0]["defaults"][k] == pps[0][k]

        for k in ["retention", "deployResources"]:
            assert data["pipelines_providers"][0][k] == pps[0][k]
