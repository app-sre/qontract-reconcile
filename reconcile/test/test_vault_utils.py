import importlib
import logging
import os
import time
from unittest.mock import (
    MagicMock,
    patch,
)

import hvac.exceptions
import pytest

from reconcile.utils import vault


class SleepCalledError(Exception):
    pass


class VaultClientTest(vault.VaultClient):
    def __init__(self) -> None:
        pass

    def _refresh_client_auth(self) -> None:
        pass


class TestVaultUtils:
    @staticmethod
    def test_vault_auto_refresh_env() -> None:
        os.environ["VAULT_AUTO_REFRESH_INTERVAL"] = "1"
        importlib.reload(vault)
        assert vault.VAULT_AUTO_REFRESH_INTERVAL == 1

    @staticmethod
    def test_vault_auto_refresh_no_env() -> None:
        del os.environ["VAULT_AUTO_REFRESH_INTERVAL"]
        assert os.getenv("VAULT_AUTO_REFRESH_INTERVAL") is None
        importlib.reload(vault)
        assert vault.VAULT_AUTO_REFRESH_INTERVAL == 600

    @staticmethod
    @patch.object(time, "sleep")
    def test_sleep_is_called(sleep: MagicMock) -> None:
        sleep.side_effect = SleepCalledError

        client = VaultClientTest()

        with pytest.raises(SleepCalledError):
            client._auto_refresh_client_auth()

    @staticmethod
    def test_read_all_with_version_kvv2_default_to_latest_version() -> None:
        """Test that version=None in secret defaults to SECRET_VERSION_LATEST for KV v2."""
        with patch("reconcile.utils.vault.VaultClient.__init__", return_value=None):
            client = vault.VaultClient()
            client._read_all_v2 = MagicMock(return_value=({"key": "value"}, "1"))

        with patch.object(client, "_get_mount_version_by_secret_path", return_value=2):
            result = client.read_all_with_version({
                "path": "test/secret",
                "version": None,
            })
            assert result == ({"key": "value"}, "1")
            client._read_all_v2.assert_called_once_with(
                "test/secret", vault.SECRET_VERSION_LATEST
            )


def test_refresh_client_auth_collapses_multiline_exception_message(
    tmp_path: os.PathLike[str], caplog: pytest.LogCaptureFixture
) -> None:
    """A multi-line exception message (e.g. an HTML error body with embedded
    newlines, as returned by a gateway timeout) must be logged as a single
    line rather than split across several physical log lines."""
    token_path = os.path.join(tmp_path, "token")
    with open(token_path, "w", encoding="locale") as f:
        f.write("fake-token")

    with patch("reconcile.utils.vault.VaultClient.__init__", return_value=None):
        client = vault.VaultClient()

    client.kube_auth_enabled = True
    client.kube_sa_token_path = token_path
    client.kube_auth_role = "qontract-reconcile"
    client.kube_auth_mount = "kubernetes-appsres09ue1"
    client._client = MagicMock()
    client._client.url = "https://vault.devshift.net"
    client._client.auth.kubernetes.login.side_effect = Exception(
        "<html><body><h1>504 Gateway Time-out</h1>\n"
        "The server didn't respond in time.\n"
        "</body></html>\n"
    )

    with caplog.at_level(logging.ERROR):
        client._refresh_client_auth()

    assert len(caplog.records) == 1
    logged_message = caplog.records[0].message
    assert "\n" not in logged_message
    assert "504 Gateway Time-out" in logged_message
    assert "The server didn't respond in time." in logged_message


@pytest.fixture
def kv2_client_invalid_path() -> vault.VaultClient:
    """VaultClient with KV v2 list raising InvalidPath (empty engine)."""
    with patch("reconcile.utils.vault.VaultClient.__init__", return_value=None):
        client = vault.VaultClient()
        client._client = MagicMock()
        client._client.secrets.kv.v2.list_secrets.side_effect = (
            hvac.exceptions.InvalidPath()
        )
    return client


@pytest.mark.parametrize(
    "method_name, expected",
    [
        ("_list_kv2", {}),
        ("list", []),
        ("list_all", []),
    ],
)
def test_empty_kv2_engine(
    kv2_client_invalid_path: vault.VaultClient,
    method_name: str,
    expected: dict | list[str],
) -> None:
    with patch.object(
        kv2_client_invalid_path, "_get_mount_version_by_secret_path", return_value=2
    ):
        result = getattr(kv2_client_invalid_path, method_name)("engine/some/path")
        assert result == expected
