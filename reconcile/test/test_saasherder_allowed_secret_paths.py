from collections.abc import Callable

import pytest

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.secret_reader import SecretReader


@pytest.mark.parametrize(
    "allowed_secret_parameter_path,referenced_secret_path,expected_valid",
    [
        # covered by parent directory
        ("foobar", "foobar/baz", True),
        # not covered by parent directory even though there is a common name prefix
        ("foo", "foobar/baz", False),
        # multilevel allowed path
        ("foo/bar", "foo/bar/baz", True),
        # multilevel but different intermediary path
        ("foo/bar", "foo/baz/bar", False),
    ],
)
def test_saasherder_allowed_secret_paths(
    allowed_secret_parameter_path: str,
    referenced_secret_path: str,
    expected_valid: bool,
    secret_reader: SecretReader,
    gql_class_factory: Callable[
        ...,
        SaasFile,
    ],
):
    """
    ensure a parent directory in allowed_secret_parameter_paths matches correctly
    """
    saas_files = [
        gql_class_factory(
            SaasFile,
            {
                "path": "path1",
                "name": "a1",
                "managedResourceTypes": [],
                "managedResourceNames": None,
                "allowedSecretParameterPaths": [allowed_secret_parameter_path],
                "app": {"name": "app1", "selfServiceRoles": [{"name": "test"}]},
                "pipelinesProvider": {
                    "name": "tekton-app-sre-pipelines-appsres03ue1",
                    "provider": "tekton",
                    "namespace": {
                        "name": "app-sre-pipelines",
                        "cluster": {
                            "name": "appsres03ue1",
                            "serverUrl": "https://api.appsres03ue1.5nvu.p1.openshiftapps.com:6443",
                            "consoleUrl": "https://console.appsres03ue1.5nvu.p1.openshiftapps.com:6443",
                            "internal": True,
                        },
                    },
                    "defaults": {
                        "pipelineTemplates": {
                            "openshiftSaasDeploy": {"name": "openshift-saas-deploy"}
                        }
                    },
                    "pipelineTemplates": {
                        "openshiftSaasDeploy": {"name": "openshift-saas-deploy"}
                    },
                },
                "imagePatterns": [],
                "resourceTemplates": [
                    {
                        "path": "path1",
                        "name": "test",
                        "url": "url",
                        "targets": [
                            {
                                "namespace": {
                                    "name": "test-ns-subscriber",
                                    "environment": {
                                        "name": "App-SRE",
                                        "parameters": "{}",
                                    },
                                    "app": {"name": "test-saas-deployments"},
                                    "cluster": {
                                        "name": "appsres03ue1",
                                        "serverUrl": "https://api.appsres03ue1.5nvu.p1.openshiftapps.com:6443",
                                        "internal": True,
                                    },
                                },
                                "ref": "main",
                                "upstream": {
                                    "instance": {
                                        "name": "ci",
                                        "serverUrl": "https://jenkins.com",
                                    },
                                    "name": "job",
                                },
                                "parameters": "{}",
                                "secretParameters": [
                                    {
                                        "name": "secret",
                                        "secret": {
                                            "path": referenced_secret_path,
                                            "field": "db.endpoint",
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        )
    ]

    saasherder = SaasHerder(
        saas_files,
        secret_reader=secret_reader,
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=7,
        repo_url="https://repo-url.com",
        validate=True,
    )

    assert saasherder.valid == expected_valid
