from datetime import date, timedelta
from typing import Dict, List

import pytest

from reconcile import openshift_rolebindings
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.openshift_resource import (OpenshiftResource as OR,
                                                ConstructResourceError)


from .fixtures import Fixtures

fxt = Fixtures('openshift_resource')

TEST_INT = 'test_openshift_resources'
TEST_INT_VER = make_semver(1, 9, 2)

apply = Fixtures('openshift_resource') \
    .get_anymarkup('expiration_date_check.yml')


class TestOpenshiftResource:
    @staticmethod
    def test_verify_valid_k8s_object():
        resource = fxt.get_anymarkup('valid_resource.yml')
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_verify_valid_k8s_object_false():
        resource = fxt.get_anymarkup('invalid_resource.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_name_format():
        resource = fxt.get_anymarkup('invalid_resource_name_format.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_name_too_long():
        resource = fxt.get_anymarkup('invalid_resource_name_too_long.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_container_name_format():
        resource = fxt.get_anymarkup(
            'invalid_resource_container_name_format.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_container_name_too_long():
        resource = fxt.get_anymarkup(
            'invalid_resource_container_name_too_long.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_annotates_resource():
        resource = fxt.get_anymarkup('annotates_resource.yml')
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.has_qontract_annotations() is False

        annotated = openshift_resource.annotate()
        assert annotated.has_qontract_annotations() is True

    @staticmethod
    def test_sha256sum_properly_ignores_some_params():
        resources = fxt.get_anymarkup('ignores_params.yml')

        assert OR(resources[0],
                  TEST_INT,
                  TEST_INT_VER).annotate().sha256sum() == \
            OR(resources[1], TEST_INT, TEST_INT_VER).annotate().sha256sum()

    @staticmethod
    def test_sha256sum():
        resource = fxt.get_anymarkup('sha256sum.yml')

        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.sha256sum() == \
            '1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965'

        annotated = openshift_resource.annotate()

        assert annotated.sha256sum() == \
            '1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965'

        assert annotated.has_valid_sha256sum()

        annotated.body['metadata']['annotations']['qontract.sha256sum'] = \
            'test'

        assert annotated.sha256sum() == \
            '1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965'

        assert not annotated.has_valid_sha256sum()

    @staticmethod
    def test_has_owner_reference_true():
        resource = {
            'kind': 'kind',
            'metadata': {
                'name': 'resource',
                'ownerReferences': [
                    {
                        'name': 'owner'
                    }
                ]
            }
        }
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.has_owner_reference()

    @staticmethod
    def test_has_owner_reference_false():
        resource = {
            'kind': 'kind',
            'metadata': {
                'name': 'resource'
            }
        }
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert not openshift_resource.has_owner_reference()

    @staticmethod
    def test_check_temp_role_after_expiration_date():
        expiration_date = date.today() - \
                timedelta(days=(openshift_rolebindings.EXPIRATION_MAX+1))
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not openshift_rolebindings \
                .role_still_valid(r['expirationDate'])

    @staticmethod
    def test_check_temp_role_before_expiration_date():
        expiration_date = date.today() + \
                timedelta(days=(openshift_rolebindings.EXPIRATION_MAX-1))
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert openshift_rolebindings \
                .role_still_valid(r['expirationDate'])

    @staticmethod
    def test_check_temp_role_no_expiration_date():
        resource = mock_openshift_role_bindings_no_expiration_date()
        for r in resource:
            assert openshift_rolebindings \
                .has_valid_expiration_date(r['expirationDate'])

    @staticmethod
    def test_has_no_date_format():
        resource = mock_openshift_role_bindings_no_expiration_date()
        for r in resource:
            assert openshift_rolebindings \
                .role_still_valid(r['expirationDate'])

    @staticmethod
    def test_has_correct_date_format():
        expiration_date = date.today() + \
                timedelta(days=(openshift_rolebindings.EXPIRATION_MAX-1))
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert openshift_rolebindings \
                .has_valid_expiration_date(r['expirationDate'])

    @staticmethod
    def test_has_incorrect_date_format():
        expiration_date = 'invalid-date-format'
        resource = mock_openshift_role_bindings(expiration_date)
        for r in resource:
            assert not openshift_rolebindings \
                .has_valid_expiration_date(r['expirationDate'])


def mock_openshift_role_bindings(expirationDate: str) -> List[Dict]:
    openshift_rolebindings_roles = apply['gql_response']
    openshift_rolebindings_roles[0]['expirationDate'] = str(expirationDate)
    return openshift_rolebindings_roles


def mock_openshift_role_bindings_no_expiration_date() -> List[Dict]:
    openshift_rolebindings_roles = apply['gql_response']
    return openshift_rolebindings_roles
