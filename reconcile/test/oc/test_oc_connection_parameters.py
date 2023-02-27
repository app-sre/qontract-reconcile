from unittest.mock import create_autospec

import pytest

from reconcile.test.oc.fixtures import (
    load_cluster_for_connection_parameters,
    load_namespace_for_connection_parameters,
)
from reconcile.utils.oc_connection_parameters import OCConnectionParameters
from reconcile.utils.secret_reader import SecretReaderBase


@pytest.mark.parametrize(
    "cluster, use_jump_host, expected_parameters",
    [
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


def test_missing_jumphost_settings_cluster():
    test_cluster = load_cluster_for_connection_parameters("cluster_no_jumphost.yml")
    secret_reader = create_autospec(SecretReaderBase)
    with pytest.raises(RuntimeError) as e:
        OCConnectionParameters.from_cluster(
            secret_reader=secret_reader,
            cluster=test_cluster,
            use_jump_host=True,
        )
    assert (
        str(e.value)
        == "Cannot use jumphost. Cluster test-cluster does not have any jumphost settings."
    )


def test_missing_jumphost_settings_namespace():
    test_namespace = load_namespace_for_connection_parameters("namespace_no_admin.yml")
    secret_reader = create_autospec(SecretReaderBase)
    with pytest.raises(RuntimeError) as e:
        OCConnectionParameters.from_namespace(
            secret_reader=secret_reader,
            namespace=test_namespace,
            use_jump_host=True,
        )
    assert (
        str(e.value)
        == "Cannot use jumphost. Cluster test-cluster does not have any jumphost settings."
    )
