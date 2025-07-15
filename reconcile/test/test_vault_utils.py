import importlib
import os
import time
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from reconcile.utils import vault


class SleepCalledError(Exception):
    pass


class TestVaultClient(vault._VaultClient):  # pylint: disable=W0223
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
        sleep.side_effect = SleepCalledError

        TestVaultClient._refresh_client_auth = MagicMock()

        client = TestVaultClient()

        with pytest.raises(SleepCalledError):
            client._auto_refresh_client_auth()
