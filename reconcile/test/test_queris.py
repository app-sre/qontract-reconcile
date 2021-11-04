from unittest import TestCase
from unittest.mock import create_autospec, patch

from reconcile import queries
from reconcile.utils import gql

from .fixtures import Fixtures

PERMISSIONS_QUERY = """
{
  permissions: permissions_v1 {
    service
    ...on PermissionSlackUsergroup_v1 {
      channels
      description
      handle
      ownersFromRepos
      pagerduty {
          name
          instance {
            name
          }
          scheduleID
          escalationPolicyID
        }
      roles {
        users {
            name
            org_username
            slack_username
            pagerduty_username
        }
    }
      schedule {
          schedule {
            start
            end
            users {
              org_username
              slack_username
            }
          }
        }
      workspace {
        name
        token {
          path
          field
        }
        api_client {
          global {
            max_retries
            timeout
          }
          methods {
            name
            args
          }
        }
        managedUsergroups
      }
    }
  }
}
"""


class TestQueris(TestCase):
    @patch.object(gql, "get_api")
    def test_get_permissions_return_all_slack_usergroup(self, get_api):
        gqlapi_mock = create_autospec(gql.GqlApi)
        gql.get_api.return_value = gqlapi_mock
        gqlapi_mock.query(PERMISSIONS_QUERY).return_value = \
            self.get_permissions_fixture()
        result = queries.get_permissions()
        self.assertTrue(all(x['service'] == 'slack-usergroup' for x in result))

    @staticmethod
    def get_permissions_fixture():
        fxt = Fixtures('slack_usergroups')
        permission = fxt.get_anymarkup('permissions.yml')
        return permission['permissions']
