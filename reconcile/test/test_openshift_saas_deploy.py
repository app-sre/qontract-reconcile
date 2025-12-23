from collections.abc import Callable
from pathlib import Path
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
from reconcile.utils.saasherder.saasherder import UNIQUE_SAAS_FILE_ENV_COMBO_LEN


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
        == "https://console.url/k8s/ns/namespace_name/tekton.dev~v1~Pipeline/o-saas-deploy-saas_name/"
        "Runs?name=saas_name-production"
    )


def test_compose_console_url_with_medium_saas_name(
    saas_file_builder: Callable[..., SaasFile],
) -> None:
    saas_name = "saas-openshift-cert-manager-routes"
    saas_file = saas_file_builder(saas_name)
    env_name = "app-sre-production"

    url = compose_console_url(saas_file, env_name)

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
    env_name = "app-sre-production"

    with pytest.raises(OpenshiftTektonResourcesNameTooLongError) as e:
        compose_console_url(saas_file, env_name)

    assert (
        f"Pipeline name o-saas-deploy-{saas_name} is longer than 56 characters"
        == str(e.value)
    )


def test_slack_notify_skipped_success() -> None:
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


def test_slack_notify_unskipped_success() -> None:
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


def test_slack_notify_unskipped_failure() -> None:
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


def test_slack_notify_skipped_failure() -> None:
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


def test_slack_notify_skipped_in_progress() -> None:
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


def test_slack_notify_failure_with_send_logs_attaches_log_file(tmp_path: Path) -> None:
    """Test that log file is attached when deployment fails with send_logs=True"""
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()

    # Create a fake log file
    io_dir = tmp_path / "logs"
    io_dir.mkdir()
    log_file = io_dir / "test-action"
    log_file.write_text("Test log content")

    actions = [{"name": "test-action", "cluster": "test-cluster", "kind": "Deployment", "action": "create"}]

    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        send_logs=True,
        io_dir=str(io_dir),
        actions=actions,
    )

    # Verify attach_filepath was set before calling chat_post_message
    assert api.attach_filepath == str(log_file)
    api.chat_post_message.assert_called_once()


def test_slack_notify_failure_without_send_logs_no_attachment(tmp_path: Path) -> None:
    """Test that log file is NOT attached when send_logs=False"""
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()

    # Create a fake log file
    io_dir = tmp_path / "logs"
    io_dir.mkdir()
    log_file = io_dir / "test-action"
    log_file.write_text("Test log content")

    actions = [{"name": "test-action", "cluster": "test-cluster", "kind": "Deployment", "action": "create"}]

    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        send_logs=False,
        io_dir=str(io_dir),
        actions=actions,
    )

    # Verify attach_filepath was NOT set
    assert not hasattr(api, "attach_filepath") or api.attach_filepath is None
    api.chat_post_message.assert_called_once()


def test_slack_notify_success_with_send_logs_no_attachment() -> None:
    """Test that log file is NOT attached on success even with send_logs=True"""
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()  # No error = success

    actions = [{"name": "test-action", "cluster": "test-cluster", "kind": "Deployment", "action": "create"}]

    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        send_logs=True,
        io_dir="/some/dir",
        actions=actions,
    )

    # Verify attach_filepath was NOT set on success
    assert not hasattr(api, "attach_filepath") or api.attach_filepath is None
    api.chat_post_message.assert_called_once()


def test_slack_notify_failure_send_logs_no_log_file_exists(tmp_path: Path) -> None:
    """Test that notification still works if log file doesn't exist"""
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()

    io_dir = tmp_path / "logs"
    io_dir.mkdir()
    # Don't create the log file

    actions = [{"name": "test-action", "cluster": "test-cluster", "kind": "Deployment", "action": "create"}]

    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        send_logs=True,
        io_dir=str(io_dir),
        actions=actions,
    )

    # Verify attach_filepath was NOT set since file doesn't exist
    assert not hasattr(api, "attach_filepath") or api.attach_filepath is None
    api.chat_post_message.assert_called_once()


def test_slack_notify_failure_send_logs_multiple_actions_attaches_first(tmp_path: Path) -> None:
    """Test that only the first log file is attached when multiple actions exist"""
    api = create_autospec(slack_api.SlackApi)
    ri = openshift_resource.ResourceInventory()
    ri.register_error()

    io_dir = tmp_path / "logs"
    io_dir.mkdir()

    # Create multiple log files
    log_file1 = io_dir / "action-1"
    log_file1.write_text("Log 1")
    log_file2 = io_dir / "action-2"
    log_file2.write_text("Log 2")

    actions = [
        {"name": "action-1", "cluster": "test-cluster", "kind": "Deployment", "action": "create"},
        {"name": "action-2", "cluster": "test-cluster", "kind": "Service", "action": "create"},
    ]

    slack_notify(
        saas_file_name="test-saas-file-name.yaml",
        env_name="test",
        slack=api,
        ri=ri,
        console_url="https://test.local/console",
        in_progress=False,
        skip_successful_notifications=False,
        send_logs=True,
        io_dir=str(io_dir),
        actions=actions,
    )

    # Verify only the first log file was attached
    assert api.attach_filepath == str(log_file1)
    api.chat_post_message.assert_called_once()
