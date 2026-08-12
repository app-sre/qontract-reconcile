from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import create_autospec

import pytest

from reconcile.test.oc.fixtures import (
    load_cluster_for_connection_parameters,
    load_namespace_for_connection_parameters,
)
from reconcile.utils.oc_connection_parameters import (
    OCConnectionError,
    OCConnectionParameters,
    _find_active_list_token,
    get_oc_connection_parameters_from_namespaces,
)
from reconcile.utils.secret_reader import (
    SecretNotFoundError,
    SecretReaderBase,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Helpers for list-token tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeSecret:
    path: str
    field: str = "token"
    version: int | None = None
    format: str | None = None


@dataclass
class _FakeTokenEntry:
    active: bool | None = None
    delete: bool | None = None
    secret: _FakeSecret | None = None


@dataclass
class _FakeCluster:
    name: str = "test-cluster"
    server_url: str = "https://api.example.com"
    internal: bool | None = False
    insecure_skip_tls_verify: bool | None = None
    automation_token: _FakeSecret | None = None
    cluster_admin_automation_token: _FakeSecret | None = None
    automation_tokens: list[_FakeTokenEntry] | None = None
    cluster_admin_automation_tokens: list[_FakeTokenEntry] | None = None
    disable: Any = None


_ACTIVE_SECRET = _FakeSecret(path="vault/active")
_FALLBACK_SECRET = _FakeSecret(path="vault/fallback")
_VAULT_RESPONSE = {"server": "https://api.example.com", "token": "tok", "username": "u"}


# ---------------------------------------------------------------------------
# _find_active_list_token unit tests
# ---------------------------------------------------------------------------


def test_find_active_list_token_returns_none_for_empty() -> None:
    assert _find_active_list_token(None) is None
    assert _find_active_list_token([]) is None


def test_find_active_list_token_skips_inactive() -> None:
    entries = [_FakeTokenEntry(active=False, secret=_ACTIVE_SECRET)]
    assert _find_active_list_token(entries) is None


def test_find_active_list_token_skips_delete_flagged() -> None:
    entries = [_FakeTokenEntry(active=True, delete=True, secret=_ACTIVE_SECRET)]
    assert _find_active_list_token(entries) is None


def test_find_active_list_token_skips_no_secret() -> None:
    entries = [_FakeTokenEntry(active=True, secret=None)]
    assert _find_active_list_token(entries) is None


def test_find_active_list_token_returns_first_active() -> None:
    second = _FakeSecret(path="vault/second")
    entries = [
        _FakeTokenEntry(active=False, secret=_ACTIVE_SECRET),
        _FakeTokenEntry(active=True, secret=second),
    ]
    assert _find_active_list_token(entries) is second


# ---------------------------------------------------------------------------
# from_cluster: list token takes priority over singular automationToken
# ---------------------------------------------------------------------------


def test_from_cluster_prefers_list_token_over_singular() -> None:
    cluster = _FakeCluster(
        automation_tokens=[_FakeTokenEntry(active=True, secret=_ACTIVE_SECRET)],
        automation_token=_FALLBACK_SECRET,
    )
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_all_secret.return_value = _VAULT_RESPONSE

    params = OCConnectionParameters.from_cluster(
        cluster=cluster, secret_reader=secret_reader, cluster_admin=False
    )

    assert params.automation_token == "tok"
    secret_reader.read_all_secret.assert_called_once_with(_ACTIVE_SECRET)


def test_from_cluster_falls_back_to_singular_when_no_active_list_entry() -> None:
    cluster = _FakeCluster(
        automation_tokens=[_FakeTokenEntry(active=False, secret=_ACTIVE_SECRET)],
        automation_token=_FALLBACK_SECRET,
    )
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_all_secret.return_value = _VAULT_RESPONSE

    params = OCConnectionParameters.from_cluster(
        cluster=cluster, secret_reader=secret_reader, cluster_admin=False
    )

    assert params.automation_token == "tok"
    secret_reader.read_all_secret.assert_called_once_with(_FALLBACK_SECRET)


def test_from_cluster_admin_prefers_list_token() -> None:
    cluster = _FakeCluster(
        cluster_admin_automation_tokens=[_FakeTokenEntry(active=True, secret=_ACTIVE_SECRET)],
        cluster_admin_automation_token=_FALLBACK_SECRET,
    )
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_all_secret.return_value = _VAULT_RESPONSE

    params = OCConnectionParameters.from_cluster(
        cluster=cluster, secret_reader=secret_reader, cluster_admin=True
    )

    assert params.cluster_admin_automation_token == "tok"
    secret_reader.read_all_secret.assert_called_once_with(_ACTIVE_SECRET)


def test_from_cluster_without_list_attr_uses_singular() -> None:
    """Clusters from GQL queries that don't include automationTokens still work."""
    test_cluster = load_cluster_for_connection_parameters("cluster_no_jumphost.yml")
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_all_secret.return_value = {
        "server": "server-url", "token": "secret1", "username": "foo"
    }

    params = OCConnectionParameters.from_cluster(
        secret_reader=secret_reader, cluster=test_cluster, cluster_admin=False
    )
    assert params.automation_token == "secret1"


def test_from_cluster() -> None:
    test_cluster = load_cluster_for_connection_parameters("cluster_no_jumphost.yml")
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret2"]
    secret_reader.read_all_secret.side_effect = [
        {"server": "server-url", "token": "secret1", "username": "foo"}
    ]

    parameters = OCConnectionParameters.from_cluster(
        secret_reader=secret_reader,
        cluster=test_cluster,
        cluster_admin=False,
    )
    assert parameters == OCConnectionParameters(
        cluster_name="test-cluster",
        server_url="server-url",
        automation_token="secret1",
        cluster_admin_automation_token=None,
        disabled_integrations=[],
        is_cluster_admin=False,
        is_internal=False,
        skip_tls_verify=None,
    )


def test_wrong_server_url() -> None:
    test_cluster = load_cluster_for_connection_parameters("cluster_no_jumphost.yml")
    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret2"]
    secret_reader.read_all_secret.side_effect = [
        {"server": "wrong", "token": "secret1", "username": "foo"}
    ]

    with pytest.raises(OCConnectionError):
        parameters = OCConnectionParameters.from_cluster(
            secret_reader=secret_reader,
            cluster=test_cluster,
            cluster_admin=False,
        )

        assert parameters is None


def test_custom_token_field() -> None:
    test_cluster = load_cluster_for_connection_parameters("cluster_custom_token.yml")

    secret_reader = create_autospec(SecretReaderBase)
    secret_reader.read_secret.side_effect = ["secret2"]
    secret_reader.read_all_secret.side_effect = [
        {"server": "server-url", "automationToken": "secret1", "username": "foo"}
    ]

    parameters = OCConnectionParameters.from_cluster(
        secret_reader=secret_reader,
        cluster=test_cluster,
        cluster_admin=False,
    )
    assert parameters.automation_token == "secret1"


@dataclass
class ExpectedConnection:
    cluster_name: str
    automation_token: str | None
    cluster_admin_automation_token: str | None
    is_cluster_admin: bool

    def to_parameters(self) -> OCConnectionParameters:
        return OCConnectionParameters(
            cluster_name=self.cluster_name,
            server_url="server-url",
            automation_token=self.automation_token,
            cluster_admin_automation_token=self.cluster_admin_automation_token,
            disabled_integrations=[],
            is_cluster_admin=self.is_cluster_admin,
            is_internal=False,
            skip_tls_verify=None,
        )


@pytest.mark.parametrize(
    "namespaces, is_cluster_admin, mock_secrets, expected_parameters",
    [
        (
            # No duplicated namespaces
            ["namespace_with_admin", "namespace_no_admin"],
            False,
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
            True,
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
            True,
            [
                ExpectedConnection(
                    cluster_name="cluster-without-admin",
                    automation_token=None,
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
            ],
        ),
        (
            # SecretNotFound error from vault
            ["namespace_with_admin"],
            False,
            False,
            [
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token=None,
                    cluster_admin_automation_token=None,
                    is_cluster_admin=False,
                ),
                ExpectedConnection(
                    cluster_name="cluster-with-admin",
                    automation_token=None,
                    cluster_admin_automation_token=None,
                    is_cluster_admin=True,
                ),
            ],
        ),
    ],
)
def test_from_namespaces(
    namespaces: list[str],
    is_cluster_admin: bool,
    mock_secrets: bool,
    expected_parameters: list[ExpectedConnection],
) -> None:
    parsed_namespaces = [
        load_namespace_for_connection_parameters(f"{ns}.yml") for ns in namespaces
    ]
    secret_reader = create_autospec(SecretReaderBase)

    if mock_secrets:
        secret_reader.read_secret.return_value = "secret"
        secret_reader.read_all_secret.return_value = {
            "server": "server-url",
            "token": "secret",
            "username": "foo",
        }
    else:
        secret_reader.read_all_secret.side_effect = SecretNotFoundError("secret")
        secret_reader.read_secret.side_effect = SecretNotFoundError("secret")

    def _sort(items: Iterable[OCConnectionParameters]) -> list[OCConnectionParameters]:
        return sorted(items, key=lambda x: (x.cluster_name, str(x.automation_token)))

    parameters = get_oc_connection_parameters_from_namespaces(
        secret_reader=secret_reader,
        namespaces=parsed_namespaces,
        cluster_admin=is_cluster_admin,
        thread_pool_size=1,
    )

    expected = [param.to_parameters() for param in expected_parameters]

    # This line is nice for debugging output
    sorted_parameters, sorted_expected = _sort(parameters), _sort(expected)

    assert sorted_parameters == sorted_expected
