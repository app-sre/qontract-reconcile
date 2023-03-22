from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
)

import pytest
from pytest_mock import MockerFixture

import reconcile.typed_queries.saas_files
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
    get_namespaces,
    get_namespaces_by_selector,
    get_saas_files,
    get_saasherder_settings,
)
from reconcile.utils.exceptions import ParameterError


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("typed_queries")


@pytest.fixture
def q(fxt: Fixtures, data_factory: Callable) -> Callable:
    def _q(
        fixture_file: str, gql_class: type, key: str
    ) -> Callable[..., dict[str, Any]]:
        def __q(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raw_data = fxt.get_anymarkup(fixture_file)
            return {key: [data_factory(gql_class, item) for item in raw_data[key]]}

        return __q

    return _q


def test_get_namespaces(q: Callable) -> None:
    items = get_namespaces(
        query_func=q("saas_files_namespaces.yml", SaasTargetNamespace, "namespaces")
    )
    assert len(items) == 6
    assert items[0].name == "example-01"


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
    q: Callable, json_path_selectors: Mapping[str, Any], expected_namespaces: list[str]
) -> None:
    items = get_namespaces_by_selector(
        query_func=q("saas_files_namespaces.yml", SaasTargetNamespace, "namespaces"),
        namespace_selector=SaasResourceTemplateTargetNamespaceSelectorV1(
            **json_path_selectors
        ),
    )
    assert sorted([item.name for item in items]) == sorted(expected_namespaces)


def test_create_targets_for_namespace_selector(
    q: Callable, gql_class_factory: Callable
) -> None:
    items = create_targets_for_namespace_selector(
        query_func=q("saas_files_namespaces.yml", SaasTargetNamespace, "namespaces"),
        target=gql_class_factory(
            SaasResourceTemplateTargetV2,
            {
                "ref": "main",
                "parameters": '{"FOO": "BAR"}',
            },
        ),
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
                                        "environment": {"name": "test"},
                                        "app": {"name": "app-02"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "main",
                                },
                                {
                                    "namespace": {
                                        "name": "namespace-prod",
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
                                        "environment": {"name": "production"},
                                        "app": {"name": "example"},
                                        "cluster": CLUSTER,
                                    },
                                    "ref": "1234567890123456789012345678901234567890",
                                },
                                {
                                    "namespace": {
                                        "name": "example-02",
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
    q: Callable,
    gql_class_factory: Callable,
    mocker: MockerFixture,
    name: Optional[str],
    env_name: Optional[str],
    app_name: Optional[str],
    fxt_file: str,
    expected_saas_files: list[dict[str, Any]],
) -> None:
    namespaces = get_namespaces(
        query_func=q("saas_files_namespaces.yml", SaasTargetNamespace, "namespaces")
    )
    get_namespaces_mock = mocker.patch.object(
        reconcile.typed_queries.saas_files, "get_namespaces"
    )
    get_namespaces_mock.return_value = namespaces

    items = get_saas_files(
        query_func=q(fxt_file, SaasFileV2, "saas_files"),
        name=name,
        env_name=env_name,
        app_name=app_name,
    )
    assert items == [gql_class_factory(SaasFile, item) for item in expected_saas_files]


def test_get_saasherder_settings(q: Callable) -> None:
    setting = get_saasherder_settings(
        query_func=q("saas_files_settings.yml", AppInterfaceSettingsV1, "settings"),
    )
    assert setting.repo_url == "https://repo-url"
    assert setting.hash_length == 42
