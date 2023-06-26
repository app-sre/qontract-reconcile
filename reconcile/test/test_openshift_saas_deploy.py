from collections.abc import Callable

import pytest

from reconcile.openshift_saas_deploy import compose_console_url
from reconcile.openshift_tekton_resources import (
    OpenshiftTektonResourcesNameTooLongError,
)
from reconcile.typed_queries.saas_files import SaasFile


@pytest.fixture
def saas_file_builder(
    gql_class_factory: Callable[..., SaasFile]
) -> Callable[..., SaasFile]:
    def builder(saas_name: str) -> SaasFile:
        return gql_class_factory(
            SaasFile,
            {
                "name": saas_name,
                "app": {"name": "app_name"},
                "pipelinesProvider": {
                    "namespace": {
                        "name": "namespace_name",
                        "cluster": {"consoleUrl": "https://console.url"},
                    },
                    "defaults": {
                        "pipelineTemplates": {
                            "openshiftSaasDeploy": {"name": "saas-deploy"}
                        },
                    },
                },
                "managedResourceTypes": [],
                "imagePatterns": [],
                "resourceTemplates": [],
            },
        )

    return builder


def test_compose_console_url(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_file = saas_file_builder("saas_name")
    env_name = "production"

    url = compose_console_url(saas_file, env_name)

    assert (
        url
        == "https://console.url/k8s/ns/namespace_name/tekton.dev~v1beta1~Pipeline/o-saas-deploy-saas_name/"
        "Runs?name=saas_name-production"
    )


def test_compose_console_url_with_medium_saas_name(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_name = "saas-openshift-cert-manager-routes"
    saas_file = saas_file_builder(saas_name)
    env_name = "app-sre-production"

    url = compose_console_url(saas_file, env_name)

    expected_run_name = f"{saas_name}-{env_name}"[:50]
    assert (
        url == "https://console.url/k8s/ns/namespace_name/tekton.dev~v1beta1~Pipeline/"
        "o-saas-deploy-saas-openshift-cert-manager-routes/"
        f"Runs?name={expected_run_name}"
    )


def test_compose_console_url_with_long_saas_name(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_name = "this-is-a-very-looooooooooooooooooooooong-saas-name"
    saas_file = saas_file_builder(saas_name)
    env_name = "app-sre-production"

    with pytest.raises(OpenshiftTektonResourcesNameTooLongError) as e:
        compose_console_url(saas_file, env_name)

    assert (
        f"Pipeline name o-saas-deploy-{saas_name} is longer than 56 characters"
        == str(e.value)
    )
