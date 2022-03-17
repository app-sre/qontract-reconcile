from datetime import date, timedelta
from typing import Dict, List

import pytest

from reconcile.utils import expiration


from .fixtures import Fixtures

apply = Fixtures("expiration").get_anymarkup("expiration_date_check.yml")


class TestRoleExpiration:
    @staticmethod
    def test_check_temp_role_after_expiration_date():
        expiration_date = date.today() + timedelta(days=1)
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert expiration.role_still_valid(r["expirationDate"])

    @staticmethod
    def test_check_temp_role_before_expiration_date():
        expiration_date = date.today() - timedelta(days=1)
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not expiration.role_still_valid(r["expirationDate"])

    @staticmethod
    def test_check_temp_role_no_expiration_date():
        resource = mock_openshift_role_bindings_no_expiration_date()
        for r in resource:
            assert expiration.has_valid_expiration_date(r["expirationDate"])

    @staticmethod
    def test_has_correct_date_format():
        expiration_date = date.today()
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert expiration.has_valid_expiration_date(r["expirationDate"])

    @staticmethod
    def test_has_incorrect_date_format():
        expiration_date = "invalid-date-format"
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not expiration.has_valid_expiration_date(r["expirationDate"])


def mock_openshift_role_bindings(expirationDate: str) -> List[Dict]:
    openshift_rolebindings_roles = apply["gql_response"]
    openshift_rolebindings_roles[0]["expirationDate"] = str(expirationDate)
    return openshift_rolebindings_roles


def mock_openshift_role_bindings_no_expiration_date() -> List[Dict]:
    openshift_rolebindings_roles = apply["gql_response"]
    return openshift_rolebindings_roles


class TestRoleExpirationFilter:
    @staticmethod
    def test_valid_roles():
        roles = [{"expirationDate": "2500-01-01"}, {"expirationDate": "1990-01-01"}]
        filtered = expiration.filter(roles)
        assert len(filtered) == 1
        assert filtered[0]["expirationDate"] == "2500-01-01"

    @staticmethod
    def test_no_roles():
        roles = [{"expirationDate": "1990-01-01"}]
        filtered = expiration.filter(roles)
        assert len(filtered) == 0

    @staticmethod
    def test_invalid_format():
        roles = [{"expirationDate": "25000101"}]
        with pytest.raises(ValueError):
            expiration.filter(roles)
