from unittest.mock import create_autospec

import pytest

from reconcile.test.oc.fixtures import (
    load_cluster_for_connection_parameters,
    load_namespace_for_connection_parameters,
)
from reconcile.utils.oc_connection_parameters import (
    OCConnectionParameters,
    get_oc_connection_parameters_from_namespaces,
)
from reconcile.utils.secret_reader import SecretReaderBase


@pytest.mark.parametrize(
    "cluster, use_jump_host, expected_parameters",
    [
        # No jumphost settings and --no-jump-host flag
        (
            "cluster_no_jumphost",
            False,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
        # No jumphost settings and --use-jump-host flag
        (
            "cluster_no_jumphost",
            True,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
        # Jumphost settings and --use-jump-host flag
        (
            "cluster_with_jumphost",
            True,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname="jumphost",
                jumphost_key="secret2",
                jumphost_known_hosts="/path/to/file",
                jumphost_user="jumphost-user",
                jumphost_remote_port=8888,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=True,
                skip_tls_verify=None,
            ),
        ),
        # Jumphost settings, but --no-jump-host flag given
        (
            "cluster_with_jumphost",
            False,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=True,
                skip_tls_verify=None,
            ),
        ),
    ],
)
def test_from_cluster(
    cluster: str, expected_parameters: OCConnectionParameters, use_jump_host: bool
):
    test_cluster = load_cluster_for_connection_parameters(f"{cluster}.yml")
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret1", "secret2"]
    parameters = OCConnectionParameters.from_cluster(
        secret_reader=secret_reader,
        cluster=test_cluster,
        use_jump_host=use_jump_host,
    )

    assert parameters == expected_parameters


@pytest.mark.parametrize(
    "namespace, use_jump_host, expected_parameters",
    [
        # No jumphost settings and --no-jump-host flag
        (
            "namespace_no_admin",
            False,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
        # No jumphost settings and --use-jump-host flag
        (
            "namespace_no_admin",
            True,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token=None,
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=None,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
        # Jumphost settings and --use-jump-host flag
        (
            "namespace_with_admin",
            True,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token="secret3",
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname="jumphost",
                jumphost_key="secret2",
                jumphost_known_hosts="/path/to/file",
                jumphost_user="jumphost-user",
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=True,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
        # Jumphost settings and --no-jump-host flag
        (
            "namespace_with_admin",
            False,
            OCConnectionParameters(
                cluster_name="test-cluster",
                server_url="server-url",
                automation_token="secret1",
                cluster_admin_automation_token="secret2",
                disabled_e2e_tests=[],
                disabled_integrations=[],
                jumphost_port=None,
                jumphost_hostname=None,
                jumphost_key=None,
                jumphost_known_hosts=None,
                jumphost_user=None,
                jumphost_remote_port=None,
                jumphost_local_port=None,
                is_cluster_admin=True,
                is_internal=False,
                skip_tls_verify=None,
            ),
        ),
    ],
)
def test_from_namespace(
    namespace: str, expected_parameters: OCConnectionParameters, use_jump_host: bool
):
    test_namespace = load_namespace_for_connection_parameters(f"{namespace}.yml")
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret1", "secret2", "secret3"]
    parameters = OCConnectionParameters.from_namespace(
        secret_reader=secret_reader,
        namespace=test_namespace,
        use_jump_host=use_jump_host,
    )

    assert parameters == expected_parameters


def test_multiple_namespaces_with_same_cluster():
    test_namespaces = [
        load_namespace_for_connection_parameters(
            "namespace_with_admin.yml"
        ),  # test-cluster
        load_namespace_for_connection_parameters(
            "namespace_with_admin.yml"
        ),  # test-cluster
        load_namespace_for_connection_parameters(
            "namespace_no_admin.yml"
        ),  # test-cluster
        load_namespace_for_connection_parameters(
            "namespace_no_admin_2.yml"
        ),  # test-cluster-2
    ]
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret"] * 10
    parameters = sorted(
        get_oc_connection_parameters_from_namespaces(
            secret_reader=secret_reader,
            namespaces=test_namespaces,
            use_jump_host=True,
        ),
        key=lambda x: x.cluster_name,
    )

    assert len(parameters) == 3

    privileged_cluster = parameters[0]
    unprivileged_cluster_1 = parameters[1]
    unprivileged_cluster_2 = parameters[2]

    assert privileged_cluster.cluster_name == "test-cluster"
    assert privileged_cluster.automation_token == "secret"
    assert privileged_cluster.cluster_admin_automation_token == "secret"
    assert privileged_cluster.is_cluster_admin

    assert unprivileged_cluster_1.cluster_name == "test-cluster"
    assert not unprivileged_cluster_1.is_cluster_admin
    assert unprivileged_cluster_1.automation_token == "secret"
    assert not unprivileged_cluster_1.cluster_admin_automation_token

    assert unprivileged_cluster_2.cluster_name == "test-cluster-2"
    assert not unprivileged_cluster_2.is_cluster_admin
    assert unprivileged_cluster_2.automation_token == "secret"
    assert not unprivileged_cluster_2.cluster_admin_automation_token
