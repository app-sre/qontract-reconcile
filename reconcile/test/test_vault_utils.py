import importlib
import os
import time
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from reconcile.utils import vault
from reconcile.utils.vault import SecretFormatProblem


class SleepCalled(Exception):
    pass


class testVaultClient(vault._VaultClient):  # pylint: disable=W0223
    def __init__(self):  # pylint: disable=W0231
        pass


class TestVaultUtils:
    @staticmethod
    def test_vault_auto_refresh_env():
        os.environ["VAULT_AUTO_REFRESH_INTERVAL"] = "1"
        importlib.reload(vault)
        assert vault.VAULT_AUTO_REFRESH_INTERVAL == 1

    @staticmethod
    def test_vault_auto_refresh_no_env():
        del os.environ["VAULT_AUTO_REFRESH_INTERVAL"]
        assert os.getenv("VAULT_AUTO_REFRESH_INTERVAL") is None
        importlib.reload(vault)
        assert vault.VAULT_AUTO_REFRESH_INTERVAL == 600

    @staticmethod
    @patch.object(time, "sleep")
    def test_sleep_is_called(sleep):
        sleep.side_effect = SleepCalled

        testVaultClient._refresh_client_auth = MagicMock()

        client = testVaultClient()

        with pytest.raises(SleepCalled):
            client._auto_refresh_client_auth()


def test_key_has_leading_space():
    with pytest.raises(
        SecretFormatProblem,
        match="Secret key has whitespace. Expected 'leading_space' but got ' leading_space'",
    ):
        vc = testVaultClient()
        vc._get_mount_version_by_secret_path = MagicMock(return_value=2)
        vc._read_all_v2 = MagicMock(
            return_value=({" leading_space": "leadingspace"}, 2)
        )

        vc.read_all({"path": "/secret", "version": 2})


def test_key_has_trailing_space():
    with pytest.raises(
        SecretFormatProblem,
        match="Secret key has whitespace. Expected 'trailing_space' but got 'trailing_space '",
    ):
        vc = testVaultClient()
        vc._get_mount_version_by_secret_path = MagicMock(return_value=2)
        vc._read_all_v2 = MagicMock(
            return_value=({"trailing_space ": "trailingspace"}, 2)
        )

        vc.read_all({"path": "/secret", "version": 2})


def test_key_has_nospace():
    vc = testVaultClient()
    vc._get_mount_version_by_secret_path = MagicMock(return_value=2)
    vc._read_all_v2 = MagicMock(return_value=({"nospaces": "nospaces"}, 2))

    k = vc.read_all({"path": "/secret", "version": 2})
    assert k["nospaces"] == "nospaces"


def test_key_has_padded_spaces():
    with pytest.raises(
        SecretFormatProblem,
        match="Secret key has whitespace. Expected 'padding_spaces' but got ' padding_spaces '",
    ):
        vc = testVaultClient()
        vc._get_mount_version_by_secret_path = MagicMock(return_value=2)
        vc._read_all_v2 = MagicMock(
            return_value=({" padding_spaces ": "padding_spaces"}, 2)
        )

        vc.read_all({"path": "/secret", "version": 2})
