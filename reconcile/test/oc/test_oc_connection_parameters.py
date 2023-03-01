from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional
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
                is_cluster_admin=False,
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
                is_cluster_admin=False,
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
                is_cluster_admin=False,
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
                is_cluster_admin=False,
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
        cluster_admin=False,
        use_jump_host=use_jump_host,
    )

    assert parameters == expected_parameters


@dataclass
class ExpectedConnection:
    cluster_name: str
    automation_token: Optional[str]
    cluster_admin_automation_token: Optional[str]
    is_cluster_admin: bool

    def to_parameters(self) -> OCConnectionParameters:
        return OCConnectionParameters(
            cluster_name=self.cluster_name,
            server_url="server-url",
            automation_token=self.automation_token,
            cluster_admin_automation_token=self.cluster_admin_automation_token,
            disabled_e2e_tests=[],
            disabled_integrations=[],
            jumphost_port=None,
            jumphost_hostname=None,
            jumphost_key=None,
            jumphost_known_hosts=None,
            jumphost_user=None,
            jumphost_remote_port=None,
            jumphost_local_port=None,
            is_cluster_admin=self.is_cluster_admin,
            is_internal=False,
            skip_tls_verify=None,
        )


@pytest.mark.parametrize(
    "namespaces, is_cluster_admin, expected_parameters",
    [
        (
            # No duplicated namespaces
            ["namespace_with_admin", "namespace_no_admin"],
            False,
            [
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token=None,
                    cluster_admin_automation_token="secret",
                    is_cluster_admin=True,
                ),
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
            ],
        ),
        (
            # Duplicated namespace
            ["namespace_with_admin", "namespace_with_admin", "namespace_no_admin"],
            False,
            [
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token=None,
                    cluster_admin_automation_token="secret",
                    is_cluster_admin=True,
                ),
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
            ],
        ),
        (
            # Enforce admin
            ["namespace_with_admin", "namespace_no_admin"],
            True,
            [
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token=None,
                    cluster_admin_automation_token="secret",
                    is_cluster_admin=True,
                ),
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token=None,
                    cluster_admin_automation_token="secret",
                    is_cluster_admin=True,
                ),
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
            ],
        ),
        (
            # Enforce admin on namespace w/o token
            ["namespace_no_admin_token"],
            True,
            [
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token="secret",
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token=None,
                    cluster_admin_automation_token=None,
                    is_cluster_admin=True,
                ),
            ],
        ),
        (
            # Missing automation token
            ["namespace_no_tokens"],
            False,
            [
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token=None,
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
            ],
        ),
    ],
)
def test_from_namespaces(
    namespaces: list[str],
    is_cluster_admin: bool,
    expected_parameters: list[ExpectedConnection],
):
    parsed_namespaces = [
        load_namespace_for_connection_parameters(f"{ns}.yml") for ns in namespaces
    ]
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret"] * 100

    def _sort(items: Iterable[OCConnectionParameters]) -> list[OCConnectionParameters]:
        return sorted(items, key=lambda x: (x.cluster_name, str(x.automation_token)))

    parameters = get_oc_connection_parameters_from_namespaces(
        secret_reader=secret_reader,
        namespaces=parsed_namespaces,
        cluster_admin=is_cluster_admin,
        use_jump_host=False,
        thread_pool_size=1,
    )

    expected = [param.to_parameters() for param in expected_parameters]

    # This line is nice for debugging output
    sorted_parameters, sorted_expected = _sort(parameters), _sort(expected)

    assert sorted_parameters == sorted_expected
