import pytest
from .fixtures import Fixtures

import semver

from utils.openshift_resource import (OpenshiftResource as OR,
                                      ConstructResourceError)

fxt = Fixtures('openshift_resource')

TEST_INT = 'test_openshift_resources'
TEST_INT_VER = semver.format_version(1, 9, 2)


class TestOpenshiftResource(object):
    def test_verify_valid_k8s_object(self):
        resource = fxt.get_anymarkup('valid_resource.yml')
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.verify_valid_k8s_object() is None

    def test_verify_valid_k8s_object_false(self):
        resource = fxt.get_anymarkup('invalid_resource.yml')

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    def test_annotates_resource(self):
        resource = fxt.get_anymarkup('annotates_resource.yml')
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.has_qontract_annotations() is False

        annotated = openshift_resource.annotate()
        assert annotated.has_qontract_annotations() is True

    def test_sha256sum_properly_ignores_some_params(self):
        resources = fxt.get_anymarkup('ignores_params.yml')

        assert OR(resources[0],
                  TEST_INT,
                  TEST_INT_VER).annotate().sha256sum() == \
            OR(resources[1], TEST_INT, TEST_INT_VER).annotate().sha256sum()

    def test_sha256sum(self):
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
