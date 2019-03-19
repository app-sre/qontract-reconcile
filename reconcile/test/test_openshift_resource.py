import pytest
from .fixtures import Fixtures

import semver

from utils.openshift_resource import OpenshiftResource

fxt = Fixtures('openshift_resource')

QONTRACT_INTEGRATION = 'openshift_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 3, 1)


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


class TestOpenshiftResource(object):
    def test_verify_valid_k8s_object(self):
        resource = fxt.get_anymarkup('valid_resource.yml')
        openshift_resource = OR(resource)

        assert openshift_resource.verify_valid_k8s_object() is None

    def test_verify_valid_k8s_object_false(self):
        resource = fxt.get_anymarkup('invalid_resource.yml')
        openshift_resource = OR(resource)

        with pytest.raises(KeyError):
            assert openshift_resource.verify_valid_k8s_object() is None

    def test_annotates_resource(self):
        resource = fxt.get_anymarkup('annotates_resource.yml')
        openshift_resource = OR(resource)

        assert openshift_resource.has_qontract_annotations() is False

        annotated = openshift_resource.annotate()
        assert annotated.has_qontract_annotations() is True

    def test_sha256sum_properly_ignores_some_params(self):
        resources = fxt.get_anymarkup('ignores_params.yml')

        assert OR(resources[0]).annotate().sha256sum() == \
            OR(resources[1]).annotate().sha256sum()

    def test_sha256sum(self):
        resource = fxt.get_anymarkup('sha256sum.yml')

        openshift_resource = OR(resource)

        assert openshift_resource.sha256sum() == \
            '1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965'

        annotated = openshift_resource.annotate()

        assert annotated.sha256sum() == \
            '1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965'

        annotated.body['metadata']['annotations']['qontract.sha256sum'] = \
            'test'

        assert annotated.sha256sum() == 'test'
