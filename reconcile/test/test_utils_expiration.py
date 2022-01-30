from datetime import date, timedelta
from typing import Dict, List

from reconcile.utils import expiration
from reconcile.utils.semver_helper import make_semver


from .fixtures import Fixtures

apply = Fixtures('expiration') \
    .get_anymarkup('expiration_date_check.yml')


class TestOpenshiftResource:
    @staticmethod
    def test_check_temp_role_after_expiration_date():
        expiration_date = date.today() + \
                timedelta(days=1)
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert expiration \
                .role_still_valid(r['expirationDate'])

    @staticmethod
    def test_check_temp_role_before_expiration_date():
        expiration_date = date.today() - \
                timedelta(days=1)
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not expiration \
                .role_still_valid(r['expirationDate'])

    @staticmethod
    def test_check_temp_role_no_expiration_date():
        resource = mock_openshift_role_bindings_no_expiration_date()
        for r in resource:
            assert expiration \
                .has_valid_expiration_date(r['expirationDate'])

    @staticmethod
    def test_has_correct_date_format():
        expiration_date = date.today()
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert expiration \
                .has_valid_expiration_date(r['expirationDate'])

    @staticmethod
    def test_has_incorrect_date_format():
        expiration_date = 'invalid-date-format'
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not expiration \
                .has_valid_expiration_date(r['expirationDate'])


def mock_openshift_role_bindings(expirationDate: str) -> List[Dict]:
    openshift_rolebindings_roles = apply['gql_response']
    openshift_rolebindings_roles[0]['expirationDate'] = str(expirationDate)
    return openshift_rolebindings_roles


def mock_openshift_role_bindings_no_expiration_date() -> List[Dict]:
    openshift_rolebindings_roles = apply['gql_response']
    return openshift_rolebindings_roles
