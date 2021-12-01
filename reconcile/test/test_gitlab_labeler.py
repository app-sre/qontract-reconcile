from unittest import TestCase
from unittest.mock import patch, create_autospec

from typing import Any, Optional

from reconcile.queries import APPS_QUERY
import reconcile.gitlab_labeler as gl
from reconcile.utils import gql
from .fixtures import Fixtures


class TestData:
    '''Class to add data to tests in setUp. It will be used by mocks'''
    def __init__(self):
        self._apps = []

    @property
    def apps(self) -> list[dict]:
        return self._apps

    @apps.setter  # type: ignore[no-redef, attr-defined]
    def apps(self, apps: list[dict]) -> None:
        if not isinstance(apps, list):
            raise TypeError(f'Expecting list, have {type(apps)}')
        self._apps = apps


class TestOnboardingGuesser(TestCase):

    def setUp(self) -> None:
        self.test_data = TestData()

        self.fxt = Fixtures('apps')
        self.app1 = {'path': '/services/parent/normalapp/app.yml',
                     'name': 'normalapp', 'onboardingStatus': 'BestEffort',
                     'serviceOwners':
                     [{'name': 'Service Owner',
                       'email': 'serviceowner@test.com'}],
                     'parentApp': None, 'codeComponents':
                     [{'url': 'https://github.com/test',
                       'resource': 'upstream', 'gitlabRepoOwners': None,
                       'gitlabHousekeeping': None, 'jira': None}]}

        self.app2 = {'path': '/services/parent/normalapp2/app.yml',
                     'name': 'normalapp2', 'onboardingStatus': 'BestEffort',
                     'serviceOwners':
                     [{'name': 'Service Owner',
                      'email': 'serviceowner@test.com'}],
                     'parentApp': None, 'codeComponents':
                     [{'url': 'https://github.com/test',
                       'resource': 'upstream', 'gitlabRepoOwners': None,
                       'gitlabHousekeeping': None, 'jira': None}]}

        self.app3 = {'path': '/services/parent/childapp/app.yml',
                     'name': 'childapp', 'onboardingStatus': 'BestEffort',
                     'serviceOwners':
                     [{'name': 'Service Owner',
                       'email': 'serviceowner@test.com'}],
                     'parentApp': {'path': '/services/parentapp/app.yml',
                                   'name': 'parentapp'},
                     'codeComponents':
                     [{'url': 'https://github.com/test',
                       'resource': 'upstream', 'gitlabRepoOwners': None,
                       'gitlabHousekeeping': None, 'jira': None}]}

        # Patcher for GqlApi methods
        self.gql_patcher = patch.object(gql, 'get_api', autospec=True)
        self.gql = self.gql_patcher.start()
        gqlapi_mock = create_autospec(gql.GqlApi)
        self.gql.return_value = gqlapi_mock
        gqlapi_mock.query.side_effect = self.mock_gql_query

    def mock_gql_query(self, query: str) -> Optional[dict[str, Any]]:
        '''Mock for GqlApi.query using test_data set in setUp'''
        if query == APPS_QUERY:
            return {'apps': self.test_data.apps}
        else:
            return None

    def tearDown(self) -> None:
        """ cleanup patches created in self.setUp"""
        self.gql_patcher.stop()

    def test_get_app_list(self):
        self.test_data.apps = [self.app1]
        t = gl.get_app_list()
        assert t == {'normalapp': {'onboardingStatus': 'BestEffort',
                     'parentApp': None}}

    def test_get_app_list_2(self):
        self.test_data.apps = [self.app1, self.app2]
        t = gl.get_app_list()
        self.assertEqual(t, {'normalapp': {'onboardingStatus': 'BestEffort',
                                           'parentApp': None},
                             'normalapp2': {'onboardingStatus': 'BestEffort',
                                            'parentApp': None}})

    def test_get_parents_list(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        t = gl.get_parents_list()
        self.assertEqual(t, ['parentapp'])

    def test_get_parents_list_empty(self):
        self.test_data.apps = [self.app1, self.app2]
        t = gl.get_parents_list()
        self.assertEqual(t, [])

    def test_guess_onboarding_status_child(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ['data/services/parentapp/childapp']

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        self.assertEqual(t, 'BestEffort')

    def test_guess_onboarding_status_normal(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ['data/services/normalapp2']

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        self.assertEqual(t, 'BestEffort')

    def test_guess_onboarding_status_no_app(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ['data/test/test']

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        self.assertIsNone(t)

    def test_guess_onboarding_status_key_error(self):
        self.test_data.apps = [self.app1, self.app2, self.app3]
        parents = gl.get_parents_list()
        apps = gl.get_app_list()
        changed_paths = ['data/services/normalapp3']

        t = gl.guess_onboarding_status(changed_paths, apps, parents)
        self.assertIsNone(t)
