from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
)

import pytest

from reconcile.gql_definitions.common.saas_files import (
    SaasFileV2,
    SaasResourceTemplateTargetNamespaceSelectorV1,
    SaasResourceTemplateTargetV2,
)
from reconcile.gql_definitions.common.saasherder_settings import AppInterfaceSettingsV1
from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.saas_files import (
    SaasFile,
    create_targets_for_namespace_selector,
    export_model,
    get_namespaces_by_selector,
    get_saas_files,
    get_saasherder_settings,
)
from reconcile.utils.exceptions import ParameterError


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("typed_queries")


@pytest.fixture
def query_func_from_fixture(fxt: Fixtures, data_factory: Callable) -> Callable:
    def _q(
        fixture_file: str, gql_class: type, key: str
    ) -> Callable[..., dict[str, Any]]:
        def __q(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raw_data = fxt.get_anymarkup(fixture_file)
            return {key: [data_factory(gql_class, item) for item in raw_data[key]]}

        return __q

    return _q


@pytest.fixture
def namespaces(
    gql_class_factory: Callable[..., SaasTargetNamespace], fxt: Fixtures
) -> list[SaasTargetNamespace]:
    return [
        gql_class_factory(
            SaasTargetNamespace,
            ns,
        )
        for ns in fxt.get_anymarkup("saas_files_namespaces.yml")["namespaces"]
    ]


@pytest.mark.parametrize(
    "json_path_selectors, expected_namespaces",
    [
        (
            {
                "jsonPathSelectors": {
                    "include": [],
                    "exclude": None,
                }
            },
            [],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.app.name="example"]',
                    ],
                    "exclude": None,
                }
            },
            ["example-01", "example-02"],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.app.name="example"]',
                    ],
                    "exclude": [],
                }
            },
            ["example-01", "example-02"],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.app.name="example"]',
                    ],
                    "exclude": [
                        'namespace[?@.name="example-01"]',
                    ],
                }
            },
            ["example-02"],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.cluster.name="appint-ex-01"]',
                    ],
                    "exclude": [
                        'namespace[?@.app.name="example"]',
                    ],
                }
            },
            [
                "app-interface-test-service-prod",
                "app-interface-test-service-pipelines",
                "app-interface-test-service-stage",
            ],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.environment.name="production"]',
                        'namespace[?@.environment.name="stage"]',
                    ],
                    "exclude": [
                        'namespace[?@.app.name="app-interface-test-service"]',
                        'namespace[?@.cluster.name="app-interface-infra"]',
                    ],
                }
            },
            ["example-01", "example-02"],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.environment.name="production" & @.app.name="example"]',
                    ],
                    "exclude": [],
                }
            },
            [
                "example-01",
            ],
        ),
        # by label - this attribute is a Json object
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.environment.labels.type="integration"]',
                    ],
                    "exclude": [],
                }
            },
            [
                "app-interface-integration",
            ],
        ),
        # skupper real life example
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.environment.labels.type="stage" & @.skupperSite]',
                    ],
                    "exclude": [],
                }
            },
            [
                "app-interface-test-service-prod",
                "app-interface-test-service-stage",
            ],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        "namespace[?@.skupperSite]",
                    ],
                    "exclude": [
                        'namespace[?@.environment.labels.type="stage"]',
                    ],
                }
            },
            ["app-interface-test-service-pipelines"],
        ),
        (
            {
                "jsonPathSelectors": {
                    "include": [
                        "namespace[?@.skupperSite]",
                    ],
                    "exclude": [
                        "namespace[?@.skupperSite.delete=true]",
                    ],
                }
            },
            [
                "app-interface-test-service-pipelines",
                "app-interface-test-service-prod",
            ],
        ),
        # bad json path
        pytest.param(
            {
                "jsonPathSelectors": {
                    "include": [
                        "namespace[?()GARBAGE]",
                    ],
                    "exclude": [],
                }
            },
            [],
            marks=pytest.mark.xfail(strict=True, raises=ParameterError),
        ),
        # bad json path
        pytest.param(
            {
                "jsonPathSelectors": {
                    "include": [],
                    "exclude": [
                        "namespace[?()GARBAGE]",
                    ],
                }
            },
            [],
            marks=pytest.mark.xfail(strict=True, raises=ParameterError),
        ),
    ],
)
def test_get_namespaces_by_selector(
    namespaces: list[SaasTargetNamespace],
    json_path_selectors: Mapping[str, Any],
    expected_namespaces: list[str],
) -> None:
    items = get_namespaces_by_selector(
        namespaces=namespaces,
        namespace_selector=SaasResourceTemplateTargetNamespaceSelectorV1(
            **json_path_selectors
        ),
    )
    assert sorted([item.name for item in items]) == sorted(expected_namespaces)


def test_create_targets_for_namespace_selector(
    namespaces: list[SaasTargetNamespace], gql_class_factory: Callable
) -> None:
    items = create_targets_for_namespace_selector(
        target=gql_class_factory(
            SaasResourceTemplateTargetV2,
            {
                "ref": "main",
                "parameters": '{"FOO": "BAR"}',
            },
        ),
        namespaces=namespaces,
        namespace_selector=SaasResourceTemplateTargetNamespaceSelectorV1(
            **{
                "jsonPathSelectors": {
                    "include": [
                        'namespace[?@.app.name="example"]',
                    ],
                    "exclude": [],
                }
            }
        ),
    )
    assert len(items) == 2
    assert items[0].namespace.name == "example-01"  # type: ignore
    assert items[1].namespace.name == "example-02"  # type: ignore


CLUSTER = {
    "name": "appint-ex-01",
    "serverUrl": "https://cluster-url",
    "internal": False,
    "automationToken": {
        "path": "creds",
        "field": "token",
    },
}

PIPELINE_PROVIDER = {
    "name": "pipeline-provider-01",
    "provider": "tekton",
    "namespace": {
        "name": "namespace",
        "cluster": {
            "name": "appint-ex-01",
            "serverUrl": "https://cluster-url",
            "internal": False,
            "automationToken": {"path": "creds", "field": "token"},
            "consoleUrl": "https://console-url",
        },
    },
    "defaults": {
        "pipelineTemplates": {"openshiftSaasDeploy": {"name": "openshift-saas-deploy"}}
    },
}


@pytest.mark.parametrize(
    "name, env_name, app_name, fxt_file, expected_saas_files",
    [
        (
            "saas-file-01",
            None,
            None,
            "saas_files.yml",
            [
                {
                    "path": "path1",
                    "name": "saas-file-01",
                    "app": {"name": "app-01"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "parameters": '{ "SAAS_PARAM": "foobar" }',
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "parameters": '{ "RT_PARAM": "foobar" }',
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "namespace-test",
                                        "path": "some-path",
                                        "environment": {
                                            "name": "test",
                                            "parameters": '{"ENV_PARAM": "foobar"}',
                                        },
                                        "app": {"name": "app-01"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                    "parameters": '{ "TARGET_PARAM": "foobar" }',
                                },
                                {
                                    "namespace": {
                                        "name": "namespace-prod",
                                        "path": "some-path",
                                        "environment": {"name": "prod"},
                                        "app": {"name": "app-01"},
                                        "cluster": CLUSTER,
                                    },
                                    "provider": "static",
                                    "ref": "1234567890123456789012345678901234567890",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
        (
            None,
            None,
            "app-02",
            "saas_files.yml",
            [
                {
                    "path": "path2",
                    "name": "saas-file-02",
                    "app": {"name": "app-02"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "namespace-test",
                                        "path": "some-path",
                                        "environment": {"name": "test"},
                                        "app": {"name": "app-02"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                },
                                {
                                    "namespace": {
                                        "name": "namespace-prod",
                                        "path": "some-path",
                                        "environment": {"name": "prod"},
                                        "app": {"name": "app-02"},
                                        "cluster": CLUSTER,
                                    },
                                    "provider": "static",
                                    "ref": "1234567890123456789012345678901234567890",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
        (
            None,
            "test",
            "app-02",
            "saas_files.yml",
            [
                {
                    "path": "path2",
                    "name": "saas-file-02",
                    "app": {"name": "app-02"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "namespace-test",
                                        "path": "some-path",
                                        "environment": {"name": "test"},
                                        "app": {"name": "app-02"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
        (
            None,
            "test",
            None,
            "saas_files.yml",
            [
                {
                    "path": "path1",
                    "name": "saas-file-01",
                    "app": {"name": "app-01"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "parameters": '{ "SAAS_PARAM": "foobar" }',
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "parameters": '{ "RT_PARAM": "foobar" }',
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "namespace-test",
                                        "path": "some-path",
                                        "environment": {
                                            "name": "test",
                                            "parameters": '{"ENV_PARAM": "foobar"}',
                                        },
                                        "app": {"name": "app-01"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                    "parameters": '{ "TARGET_PARAM": "foobar" }',
                                }
                            ],
                        }
                    ],
                },
                {
                    "path": "path2",
                    "name": "saas-file-02",
                    "app": {"name": "app-02"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "namespace-test",
                                        "path": "some-path",
                                        "environment": {"name": "test"},
                                        "app": {"name": "app-02"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                },
                            ],
                        }
                    ],
                },
            ],
        ),
        # with namespaceSelector
        (
            "saas-file-03",
            None,
            None,
            "saas_files.yml",
            [
                {
                    "path": "path3",
                    "name": "saas-file-03",
                    "app": {"name": "example"},
                    "pipelinesProvider": PIPELINE_PROVIDER,
                    "managedResourceTypes": [],
                    "imagePatterns": [],
                    "resourceTemplates": [
                        {
                            "name": "deploy-app",
                            "url": "https://repo-url",
                            "path": "/openshift/template.yml",
                            "targets": [
                                {
                                    "namespace": {
                                        "name": "example-01",
                                        "path": "some-path",
                                        "environment": {"name": "production"},
                                        "app": {"name": "example"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "1234567890123456789012345678901234567890",
                                },
                                {
                                    "namespace": {
                                        "name": "example-02",
                                        "path": "some-path",
                                        "environment": {"name": "stage"},
                                        "app": {"name": "example"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "1234567890123456789012345678901234567890",
                                },
                            ],
                        }
                    ],
                }
            ],
        ),
        # missing provider
        pytest.param(
            "saas-file-04",
            None,
            None,
            "saas_files-missing-provider.yml",
            [],
            marks=pytest.mark.xfail(strict=True, raises=ParameterError),
        ),
    ],
)
def test_get_saas_files(
    gql_class_factory: Callable,
    query_func_from_fixture: Callable[..., Callable],
    namespaces: list[SaasTargetNamespace],
    name: Optional[str],
    env_name: Optional[str],
    app_name: Optional[str],
    fxt_file: str,
    expected_saas_files: list[dict[str, Any]],
) -> None:
    items = get_saas_files(
        query_func=query_func_from_fixture(fxt_file, SaasFileV2, "saas_files"),
        name=name,
        env_name=env_name,
        app_name=app_name,
        namespaces=namespaces,
    )
    assert items == [gql_class_factory(SaasFile, item) for item in expected_saas_files]


def test_get_saasherder_settings(
    query_func_from_fixture: Callable[..., Callable]
) -> None:
    setting = get_saasherder_settings(
        query_func=query_func_from_fixture(
            "saas_files_settings.yml", AppInterfaceSettingsV1, "settings"
        ),
    )
    assert setting.repo_url == "https://repo-url"
    assert setting.hash_length == 42


def test_export_model(
    query_func_from_fixture: Callable[..., Callable],
    namespaces: list[SaasTargetNamespace],
) -> None:
    items = get_saas_files(
        query_func=query_func_from_fixture("saas_files.yml", SaasFileV2, "saas_files"),
        namespaces=namespaces,
    )
    saas_files = [export_model(item) for item in items]
    assert saas_files == [
        {
            "path": "path1",
            "name": "saas-file-01",
            "app": {"name": "app-01"},
            "pipelinesProvider": {
                "name": "pipeline-provider-01",
                "provider": "tekton",
                "namespace": {
                    "name": "namespace",
                    "cluster": {
                        "name": "appint-ex-01",
                        "serverUrl": "https://cluster-url",
                        "internal": False,
                        "insecureSkipTLSVerify": None,
                        "jumpHost": None,
                        "automationToken": {
                            "path": "creds",
                            "field": "token",
                            "version": None,
                            "format": None,
                        },
                        "clusterAdminAutomationToken": None,
                        "disable": None,
                        "consoleUrl": "https://console-url",
                    },
                },
                "defaults": {
                    "pipelineTemplates": {
                        "openshiftSaasDeploy": {"name": "openshift-saas-deploy"}
                    }
                },
                "pipelineTemplates": None,
            },
            "deployResources": None,
            "slack": None,
            "managedResourceTypes": [],
            "takeover": None,
            "deprecated": None,
            "compare": None,
            "timeout": None,
            "publishJobLogs": None,
            "clusterAdmin": None,
            "imagePatterns": [],
            "allowedSecretParameterPaths": None,
            "use_channel_in_image_tag": None,
            "authentication": None,
            "parameters": '{"SAAS_PARAM": "foobar"}',
            "secretParameters": None,
            "validateTargetsInApp": None,
            "resourceTemplates": [
                {
                    "name": "deploy-app",
                    "url": "https://repo-url",
                    "path": "/openshift/template.yml",
                    "provider": None,
                    "hash_length": None,
                    "parameters": '{"RT_PARAM": "foobar"}',
                    "secretParameters": None,
                    "targets": [
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "namespace-test",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "test",
                                    "labels": None,
                                    "parameters": '{"ENV_PARAM": "foobar"}',
                                    "secretParameters": None,
                                },
                                "app": {"name": "app-01", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "main",
                            "promotion": None,
                            "parameters": '{"TARGET_PARAM": "foobar"}',
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "namespace-prod",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "prod",
                                    "labels": None,
                                    "parameters": None,
                                    "secretParameters": None,
                                },
                                "app": {"name": "app-01", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "1234567890123456789012345678901234567890",
                            "promotion": None,
                            "parameters": None,
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                    ],
                }
            ],
            "selfServiceRoles": None,
        },
        {
            "path": "path2",
            "name": "saas-file-02",
            "app": {"name": "app-02"},
            "pipelinesProvider": {
                "name": "pipeline-provider-01",
                "provider": "tekton",
                "namespace": {
                    "name": "namespace",
                    "cluster": {
                        "name": "appint-ex-01",
                        "serverUrl": "https://cluster-url",
                        "internal": False,
                        "insecureSkipTLSVerify": None,
                        "jumpHost": None,
                        "automationToken": {
                            "path": "creds",
                            "field": "token",
                            "version": None,
                            "format": None,
                        },
                        "clusterAdminAutomationToken": None,
                        "disable": None,
                        "consoleUrl": "https://console-url",
                    },
                },
                "defaults": {
                    "pipelineTemplates": {
                        "openshiftSaasDeploy": {"name": "openshift-saas-deploy"}
                    }
                },
                "pipelineTemplates": None,
            },
            "deployResources": None,
            "slack": None,
            "managedResourceTypes": [],
            "takeover": None,
            "deprecated": None,
            "compare": None,
            "timeout": None,
            "publishJobLogs": None,
            "clusterAdmin": None,
            "imagePatterns": [],
            "allowedSecretParameterPaths": None,
            "use_channel_in_image_tag": None,
            "authentication": None,
            "parameters": None,
            "secretParameters": None,
            "validateTargetsInApp": None,
            "resourceTemplates": [
                {
                    "name": "deploy-app",
                    "url": "https://repo-url",
                    "path": "/openshift/template.yml",
                    "provider": None,
                    "hash_length": None,
                    "parameters": None,
                    "secretParameters": None,
                    "targets": [
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "namespace-test",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "test",
                                    "labels": None,
                                    "parameters": None,
                                    "secretParameters": None,
                                },
                                "app": {"name": "app-02", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "main",
                            "promotion": None,
                            "parameters": None,
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "namespace-prod",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "prod",
                                    "labels": None,
                                    "parameters": None,
                                    "secretParameters": None,
                                },
                                "app": {"name": "app-02", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "1234567890123456789012345678901234567890",
                            "promotion": None,
                            "parameters": None,
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                    ],
                }
            ],
            "selfServiceRoles": None,
        },
        {
            "path": "path3",
            "name": "saas-file-03",
            "app": {"name": "example"},
            "pipelinesProvider": {
                "name": "pipeline-provider-01",
                "provider": "tekton",
                "namespace": {
                    "name": "namespace",
                    "cluster": {
                        "name": "appint-ex-01",
                        "serverUrl": "https://cluster-url",
                        "internal": False,
                        "insecureSkipTLSVerify": None,
                        "jumpHost": None,
                        "automationToken": {
                            "path": "creds",
                            "field": "token",
                            "version": None,
                            "format": None,
                        },
                        "clusterAdminAutomationToken": None,
                        "disable": None,
                        "consoleUrl": "https://console-url",
                    },
                },
                "defaults": {
                    "pipelineTemplates": {
                        "openshiftSaasDeploy": {"name": "openshift-saas-deploy"}
                    }
                },
                "pipelineTemplates": None,
            },
            "deployResources": None,
            "slack": None,
            "managedResourceTypes": [],
            "takeover": None,
            "deprecated": None,
            "compare": None,
            "timeout": None,
            "publishJobLogs": None,
            "clusterAdmin": None,
            "imagePatterns": [],
            "allowedSecretParameterPaths": None,
            "use_channel_in_image_tag": None,
            "authentication": None,
            "parameters": None,
            "secretParameters": None,
            "validateTargetsInApp": None,
            "resourceTemplates": [
                {
                    "name": "deploy-app",
                    "url": "https://repo-url",
                    "path": "/openshift/template.yml",
                    "provider": None,
                    "hash_length": None,
                    "parameters": None,
                    "secretParameters": None,
                    "targets": [
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "example-01",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "production",
                                    "labels": None,
                                    "parameters": None,
                                    "secretParameters": None,
                                },
                                "app": {"name": "example", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "1234567890123456789012345678901234567890",
                            "promotion": None,
                            "parameters": None,
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                        {
                            "path": None,
                            "name": None,
                            "namespace": {
                                "name": "example-02",
                                "labels": None,
                                "delete": None,
                                "path": "some-path",
                                "environment": {
                                    "name": "stage",
                                    "labels": None,
                                    "parameters": None,
                                    "secretParameters": None,
                                },
                                "app": {"name": "example", "labels": None},
                                "cluster": {
                                    "name": "appint-ex-01",
                                    "serverUrl": "https://cluster-url",
                                    "internal": False,
                                    "insecureSkipTLSVerify": None,
                                    "jumpHost": None,
                                    "automationToken": {
                                        "path": "creds",
                                        "field": "token",
                                        "version": None,
                                        "format": None,
                                    },
                                    "clusterAdminAutomationToken": None,
                                    "disable": None,
                                },
                                "skupperSite": None,
                            },
                            "ref": "1234567890123456789012345678901234567890",
                            "promotion": None,
                            "parameters": None,
                            "secretParameters": None,
                            "upstream": None,
                            "image": None,
                            "disable": None,
                            "delete": None,
                        },
                    ],
                }
            ],
            "selfServiceRoles": None,
        },
    ]
