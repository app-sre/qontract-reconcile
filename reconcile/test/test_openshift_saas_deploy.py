from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import create_autospec

import pytest

from reconcile import slack_base
from reconcile.openshift_saas_deploy import (
    _saas_file_tekton_pipeline_name,
    compose_console_url,
    compose_grafana_logs_url,
    slack_notify,
)
from reconcile.openshift_tekton_resources import (
    OpenshiftTektonResourcesNameTooLongError,
)
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils import openshift_resource
from reconcile.utils.saasherder.saasherder import UNIQUE_SAAS_FILE_ENV_COMBO_LEN

if TYPE_CHECKING:
    from collections.abc import Callable

TEST_GRAFANA_SAAS_DEPLOY_URL = (
    "https://grafana.example.test/d/saas-deploy-logs/saas-deploy-logs"
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
                        "cluster": {
                            "name": "cluster_name",
                            "consoleUrl": "https://console.url",
                        },
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


def test_compose_grafana_logs_url(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_file = saas_file_builder("saas_name")
    pipeline_name = _saas_file_tekton_pipeline_name(saas_file)
    url = compose_grafana_logs_url(
        saas_file,
        pipeline_name=pipeline_name,
        grafana_saas_deploy_url=TEST_GRAFANA_SAAS_DEPLOY_URL,
    )
    assert (
        url == f"{TEST_GRAFANA_SAAS_DEPLOY_URL.rstrip('/')}?var-cluster=cluster_name&"
        "var-namespace=namespace_name&var-pipeline=o-saas-deploy-saas_name"
    )


def test_compose_grafana_logs_url_with_pipelinerun(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_file = saas_file_builder("saas_name")
    pipeline_name = _saas_file_tekton_pipeline_name(saas_file)
    pipelinerun_name = "test-pipelinerun-name-abcde"
    url = compose_grafana_logs_url(
        saas_file,
        pipeline_name=pipeline_name,
        grafana_saas_deploy_url=TEST_GRAFANA_SAAS_DEPLOY_URL,
        pipelinerun_name=pipelinerun_name,
    )
    assert (
        url == f"{TEST_GRAFANA_SAAS_DEPLOY_URL.rstrip('/')}?var-cluster=cluster_name&"
        "var-namespace=namespace_name&var-pipeline=o-saas-deploy-saas_name&"
        f"var-pipelinerun={pipelinerun_name}"
    )


def test_compose_console_url(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_file = saas_file_builder("saas_name")
    env_name = "production"
    pipeline_name = _saas_file_tekton_pipeline_name(saas_file)

    url = compose_console_url(saas_file, env_name, pipeline_name=pipeline_name)

    assert (
        url
        == "https://console.url/k8s/ns/namespace_name/tekton.dev~v1~Pipeline/o-saas-deploy-saas_name/"
        "Runs?name=saas_name-production"
    )


def test_compose_console_url_with_medium_saas_name(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_name = "saas-openshift-cert-manager-routes"
    saas_file = saas_file_builder(saas_name)
    env_name = "app-sre-production"
    pipeline_name = _saas_file_tekton_pipeline_name(saas_file)

    url = compose_console_url(saas_file, env_name, pipeline_name=pipeline_name)

    expected_run_name = f"{saas_name}-{env_name}"[:UNIQUE_SAAS_FILE_ENV_COMBO_LEN]
    assert (
        url == "https://console.url/k8s/ns/namespace_name/tekton.dev~v1~Pipeline/"
        "o-saas-deploy-saas-openshift-cert-manager-routes/"
        f"Runs?name={expected_run_name}"
    )


def test_compose_console_url_with_long_saas_name(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_name = "this-is-a-very-looooooooooooooooooooooong-saas-name"
    saas_file = saas_file_builder(saas_name)

    with pytest.raises(OpenshiftTektonResourcesNameTooLongError) as e:
        _saas_file_tekton_pipeline_name(saas_file)

    assert (
        f"Pipeline name o-saas-deploy-{saas_name} is longer than 56 characters"
        == str(e.value)
    )


def test_slack_notify_skipped_success() -> None:
    api = create_autospec(slack_base.SlackApi)
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


def test_slack_notify_unskipped_success() -> None:
    api = create_autospec(slack_base.SlackApi)
    slack_notify(
        saas_file_name="test-slack_notify--unskipped-success.yaml",
        env_name="test",
        slack=api,
        ri=openshift_resource.ResourceInventory(),
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        grafana_logs_url="https://test.local/grafana",
    )
    api.chat_post_message.assert_called_once_with(
        ":green_jenkins_circle: *SaaS deploy: Success*\n"
        "*SaaS File:* `test-slack_notify--unskipped-success.yaml`\n"
        "*Deployment to environment:* `test`\n"
        "<https://test.local/console|PipelineRun> | <https://test.local/grafana|Logs>"
    )


def test_slack_notify_unskipped_failure() -> None:
    api = create_autospec(slack_base.SlackApi)
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
        grafana_logs_url="https://test.local/grafana",
    )
    api.chat_post_message.assert_called_once_with(
        ":red_jenkins_circle: *SaaS deploy: Failure*\n"
        "*SaaS File:* `test-saas-file-name.yaml`\n"
        "*Deployment to environment:* `test`\n"
        "<https://test.local/console|PipelineRun> | <https://test.local/grafana|Logs>"
    )


def test_slack_notify_skipped_failure() -> None:
    api = create_autospec(slack_base.SlackApi)
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
        grafana_logs_url="https://test.local/grafana",
    )
    api.chat_post_message.assert_called_once_with(
        ":red_jenkins_circle: *SaaS deploy: Failure*\n"
        "*SaaS File:* `test-saas-file-name.yaml`\n"
        "*Deployment to environment:* `test`\n"
        "<https://test.local/console|PipelineRun> | <https://test.local/grafana|Logs>"
    )


def test_slack_notify_skipped_in_progress() -> None:
    api = create_autospec(slack_base.SlackApi)
    ri = openshift_resource.ResourceInventory()
    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=True,
        skip_successful_notifications=True,
        grafana_logs_url="https://test.local/grafana",
    )
    api.chat_post_message.assert_called_once_with(
        ":yellow_jenkins_circle: *SaaS deploy: In Progress*\n"
        "*SaaS File:* `test-saas-file-name.yaml`\n"
        "*Deployment to environment:* `test`\n"
        "<https://test.local/console|PipelineRun> | <https://test.local/grafana|Logs>\n"
        "There will not be a notice for success."
    )
