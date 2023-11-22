from collections.abc import Callable

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


def new_slack_api() -> slack_api.SlackApi:
    api = slack_api.SlackApi(
        workspace_name="test",
        token="test-token",
        init_usergroups=False,
    )

    def intercepted_slack_chat_post_message(message: str) -> str:
        # Refer to the test_slack_notify_skipped_success method for a
        # description of message_type
        global message_type
        if ":yellow_jenkins_circle:" in message:
            message_type = "in_progress"
        elif ":green_jenkins_circle:" in message:
            message_type = "success"
        elif ":red_jenkins_circle:" in message:
            message_type = "failure"
        else:
            # this shouldn't be reached. the case where a notification is
            # skipped should not have anything sent to slack for this method to
            # intercept.
            message_type = "unknown"
        return message_type

    api.chat_post_message = intercepted_slack_chat_post_message
    return api


def test_slack_notify_skipped_success():
    api = new_slack_api()
    # what type of message (if any) is being sent to Slack?
    # this can be in the set [ "in_progress", "success", "failure", "" ]
    # the empty string corresponds to no message at all because it was skipped.
    global message_type
    message_type = ""
    slack_notify(
        saas_file_name="test-slack_notify--skipped-success.yaml",
        env_name="test",
        slack=api,
        ri=openshift_resource.ResourceInventory(),
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=True,
    )
    assert (
        message_type == ""
    ), f"expected a skipped success message type to be '', but got {message_type}"


def test_slack_notify_unskipped_success():
    api = new_slack_api()
    global message_type
    message_type = ""
    slack_notify(
        saas_file_name="test-slack_notify--unskipped-success.yaml",
        env_name="test",
        slack=api,
        ri=openshift_resource.ResourceInventory(),
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
    )
    assert (
        message_type == "success"
    ), f"expected an unskipped success to be 'success', but got {message_type}"


def test_slack_notify_unskipped_failure():
    api = new_slack_api()
    global message_type
    message_type = ""
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
    assert (
        message_type == "failure"
    ), f"expected an unskipped failure to be 'falure', but got {message_type}"


def test_slack_notify_skipped_failure():
    api = new_slack_api()
    global message_type
    message_type = ""
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
    assert (
        message_type == "failure"
    ), f"expected a skipped failure to be 'failure', but got {message_type}"


def test_slack_notify_skipped_in_progress():
    api = new_slack_api()
    global message_type
    message_type = ""
    ri = openshift_resource.ResourceInventory()
    #ri.register_error()
    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=True,
        skip_successful_notifications=True,
    )
    assert (
        message_type == "in_progress"
    ), f"expected a skipped, in progress to be 'in_progress', but got {message_type}"
