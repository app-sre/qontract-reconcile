from collections.abc import Callable
from unittest.mock import create_autospec

import pytest

from reconcile.openshift_saas_deploy import (
    compose_console_url,
    slack_notify,
)
from reconcile.openshift_tekton_resources import (
    OpenshiftTektonResourcesNameTooLongError,
)
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils import (
    openshift_resource,
    slack_api,
)


@pytest.fixture
def saas_file_builder(
    gql_class_factory: Callable[..., SaasFile],
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
                "managedResourceNames": None,
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


def test_slack_notify_skipped_success():
    api = create_autospec(slack_api.SlackApi)
    slack_notify(
        saas_file_name="test-slack_notify--skipped-success.yaml",
        env_name="test",
        slack=api,
        ri=openshift_resource.ResourceInventory(),
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=True,
    )
    api.chat_post_message.assert_not_called()


def test_slack_notify_unskipped_success():
    api = create_autospec(slack_api.SlackApi)
    slack_notify(
        saas_file_name="test-slack_notify--unskipped-success.yaml",
        env_name="test",
        slack=api,
        ri=openshift_resource.ResourceInventory(),
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
    )
    api.chat_post_message.assert_called_once_with(
        ":green_jenkins_circle: SaaS file *test-slack_notify--unskipped-success.yaml* "
        "deployment to environment *test*: Success "
        "(<https://test.local/console|Open>)"
    )


def test_slack_notify_unskipped_failure():
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()
    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
    )
    api.chat_post_message.assert_called_once_with(
        ":red_jenkins_circle: SaaS file *test-saas-file-name.yaml* "
        "deployment to environment *test*: Failure "
        "(<https://test.local/console|Open>)"
    )


def test_slack_notify_skipped_failure():
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()
    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=True,
    )
    api.chat_post_message.assert_called_once_with(
        ":red_jenkins_circle: SaaS file *test-saas-file-name.yaml* "
        "deployment to environment *test*: Failure "
        "(<https://test.local/console|Open>)"
    )


def test_slack_notify_skipped_in_progress():
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=True,
        skip_successful_notifications=True,
    )
    api.chat_post_message.assert_called_once_with(
        ":yellow_jenkins_circle: SaaS file *test-saas-file-name.yaml* "
        "deployment to environment *test*: In Progress "
        "(<https://test.local/console|Open>). There will not be a notice for success."
    )
