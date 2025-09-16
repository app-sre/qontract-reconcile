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
