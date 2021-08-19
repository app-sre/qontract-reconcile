# flake8: noqa
# pylint: disable=line-too-long

from typing import Any, Callable, Dict, List, Optional

import pytest
from jinja2 import Template

from reconcile import queries
from reconcile.openshift_tekton_resources import OpenshiftTektonResources, \
    OpenshiftTektonResourcesNameTooLong, TektonNamespace

## Fixtures
@pytest.fixture
def mock_get_saas_files(monkeypatch) -> None:
    # this is a very simplified version of what get_saas_files returns, but
    # enough to give us an idea of the structures that are passed around.
    def mock_function(*args, **kwargs) -> List[Dict[str, Any]]:
        return [
            {'name': 'saas-ocm-service-log',
            'pipelinesProvider': {'name': 'tekton-ocm-pipelines-appsrep05ue1',
                                 'namespace': {'cluster': {'name': 'appsrep05ue1'},
                                              'name': 'ocm-pipelines'},
                                 'provider': 'tekton'},
            'configurableResources': True},
            {'name': 'saas-uhc-clusters-service',
            'pipelinesProvider': {'name': 'tekton-ocm-pipelines-appsrep05ue1',
                                 'namespace': {'cluster': {'name': 'appsrep05ue1'},
                                              'name': 'ocm-pipelines'},
                                 'provider': 'tekton'},
             'configurableResources': True},
            {'name': 'unleash-proxy-clowder',
            'pipelinesProvider': {'name': 'tekton-crc-pipelines-app-sre-prod-01',
                                 'namespace': {'cluster': {'name': 'app-sre-prod-01'},
                                              'name': 'crc-pipelines'},
                                 'provider': 'tekton'},
            'configurableResources': True},
            {'name': 'receptor-redis',
            'pipelinesProvider': {'name': 'tekton-crc-pipelines-app-sre-prod-01',
                                 'namespace': {'cluster': {'name': 'app-sre-prod-01'},
                                              'name': 'crc-pipelines'},
                                 'provider': 'tekton'},
            'configurableResources': True},
            {'name': 'saas-job-queue-service',
            'pipelinesProvider': {'name': 'tekton-ocm-pipelines-appsrep05ue1',
                                 'namespace': {'cluster': {'name': 'appsrep05ue1'},
                                              'name': 'ocm-pipelines'},
                                 'provider': 'tekton'},
            'configurableResources': False},
        ]

    monkeypatch.setattr(queries, 'get_saas_files', mock_function)


@pytest.fixture
def mock_empty_settings(monkeypatch) -> None:
    def mock_function() -> Dict[None, None]:
        return {}

    monkeypatch.setattr(queries, 'get_app_interface_settings', mock_function)


@pytest.fixture
def mock_non_empty_settings(monkeypatch) -> None:
    def mock_function() -> Dict[str, Any]:
        return {
            'openshiftTektonResources': {
                'images': [{
                    'name': 'qontract-reconcile',
                    'image': 'quay.io/test/qontract-reconcile',
                    'tag': 'qr-tag'
                },{
                    'name': 'ubi8',
                    'image': 'quay.io/test/ubi8-ubi-minimal',
                    'tag': 'ubi8-tag'
                }]
            }
        }

    monkeypatch.setattr(queries, 'get_app_interface_settings', mock_function)


@pytest.fixture
def mock_template_render(monkeypatch) -> None:
    def mock_function(*args, **kwargs) -> str:
        return f"metadata:\n  name: {kwargs['name']}\n"

    monkeypatch.setattr(Template, 'render', mock_function)


## Helpers
def build_otr(saas_file_name: Optional[str] = None
             ) -> OpenshiftTektonResources:
    return OpenshiftTektonResources(dry_run=False,
                                    thread_pool_size=10,
                                    internal=None,
                                    use_jump_host=False,
                                    saas_file_name=saas_file_name)


# Tests
def test_get_saas_files_no_name(mock_get_saas_files: Callable,
                                mock_empty_settings: Callable) -> None:
    otr: OpenshiftTektonResources  = build_otr()
    assert len(otr._get_saas_files()) == 4


def test_get_saas_files_name(mock_get_saas_files: Callable,
                             mock_empty_settings: Callable) -> None:
    otr: OpenshiftTektonResources = build_otr('unleash-proxy-clowder')
    assert len(otr._get_saas_files()) == 1


def test_get_saas_files_unexisting_name(mock_get_saas_files: Callable,
                                        mock_empty_settings: Callable) -> None:
    otr: OpenshiftTektonResources = build_otr('no-no-no')
    assert len(otr._get_saas_files()) == 0


def test_defaults_images(mock_empty_settings: Callable) -> None:
    otr: OpenshiftTektonResources = build_otr()
    assert otr.qr_image['image'] == 'quay.io/app-sre/qontract-reconcile'
    assert otr.qr_image['tag'] == 'latest'
    assert otr.ubi8_image['image'] == 'quay.io/app-sre/ubi8-ubi-minimal'
    assert otr.ubi8_image['tag'] == 'latest'


def test_non_defaults_images(mock_non_empty_settings: Callable) -> None:
    otr: OpenshiftTektonResources = build_otr()
    assert otr.qr_image['image'] == 'quay.io/test/qontract-reconcile'
    assert otr.qr_image['tag'] == 'qr-tag'
    assert otr.ubi8_image['image'] == 'quay.io/test/ubi8-ubi-minimal'
    assert otr.ubi8_image['tag'] == 'ubi8-tag'


def test_get_tekton_namespaces(mock_get_saas_files: Callable,
                               mock_empty_settings: Callable,
                               mock_template_render: Callable) -> None:
    otr: OpenshiftTektonResources = build_otr()

    namespaces: List[TektonNamespace] = \
        otr._build_tkn_namespaces(otr._get_saas_files())

    # This is going to test the consistency of the structure build by
    # _build_tkn_namespaces. It is especially important to verify that we have
    # only one Splunk Task and one PushGateway task and multiple
    # openshift-saas-deploy Pipelines and Tasks.
    expected = [
        {'cluster': {'name': 'appsrep05ue1'},
        'managedResourceNames': [
            {'resource': 'Task',
            'resourceNames': ['otr-push-gateway-task-status-metric',
                             'otr-push-http-splunk-tekton-pipeline-metadata',
                             'otr-saas-deploy-saas-ocm-service-log',
                             'otr-saas-deploy-saas-uhc-clusters-service']},
            {'resource': 'Pipeline',
            'resourceNames': ['otr-saas-deploy-saas-ocm-service-log',
                             'otr-saas-deploy-saas-uhc-clusters-service']}],
        'managedResourceTypeOverrides': None,
        'managedResourceTypes': ['Pipeline', 'Task'],
        'name': 'ocm-pipelines',
        'openshiftResources': [
            {'path': {'metadata': {'name': 'otr-push-gateway-task-status-metric'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-push-http-splunk-tekton-pipeline-metadata'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-saas-ocm-service-log'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-saas-ocm-service-log'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-saas-uhc-clusters-service'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-saas-uhc-clusters-service'}},
            'provider': 'openshift-tekton-resources'}]},
        {'cluster': {'name': 'app-sre-prod-01'},
        'managedResourceNames': [
            {'resource': 'Task',
            'resourceNames': ['otr-push-gateway-task-status-metric',
                             'otr-push-http-splunk-tekton-pipeline-metadata',
                             'otr-saas-deploy-unleash-proxy-clowder',
                             'otr-saas-deploy-receptor-redis']},
            {'resource': 'Pipeline',
            'resourceNames': ['otr-saas-deploy-unleash-proxy-clowder',
                             'otr-saas-deploy-receptor-redis']}],
        'managedResourceTypeOverrides': None,
        'managedResourceTypes': ['Pipeline', 'Task'],
        'name': 'crc-pipelines',
        'openshiftResources': [
            {'path': {'metadata': {'name': 'otr-push-gateway-task-status-metric'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-push-http-splunk-tekton-pipeline-metadata'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-unleash-proxy-clowder'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-unleash-proxy-clowder'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-receptor-redis'}},
            'provider': 'openshift-tekton-resources'},
            {'path': {'metadata': {'name': 'otr-saas-deploy-receptor-redis'}},
            'provider': 'openshift-tekton-resources'}]}
    ]

    assert namespaces == expected


def test_build_deploy_name_too_long() -> None:
    with pytest.raises(OpenshiftTektonResourcesNameTooLong):
        OpenshiftTektonResources.build_deploy_name(
            "this-is-a-not-accepted-very-long-name-that-will-fail")
