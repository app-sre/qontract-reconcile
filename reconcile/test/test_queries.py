from unittest import TestCase
from unittest.mock import create_autospec, patch

from reconcile import queries
from reconcile.utils import gql

from .fixtures import Fixtures


class TestQueries(TestCase):
    @patch.object(gql, "get_api", autospec=True)
    def test_get_permissions_return_all_slack_usergroup(self, mock_get_api):
        gqlapi_mock = create_autospec(gql.GqlApi)
        gqlapi_mock.query.side_effect = \
            self.get_permissions_query_side_effect
        mock_get_api.return_value = gqlapi_mock
        result = queries.get_permissions_for_slack_usergroup()
        self.assertEqual({x['service'] for x in result}, {'slack-usergroup'})

    @staticmethod
    def get_permissions_query_side_effect(query):
        if query == queries.PERMISSIONS_QUERY:
            fxt = Fixtures('slack_usergroups')
            permission = fxt.get_anymarkup('permissions.yml')
            return permission
