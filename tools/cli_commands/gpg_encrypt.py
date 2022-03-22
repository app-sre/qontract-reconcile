from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils import config
from reconcile import queries
from reconcile.utils import gpg

import json


@dataclass
class GPGEncryptCommandData:
    vault_secret_path: str
    vault_secret_version: int
    secret_file_path: str
    output: str
    target_user: str


class UserNotFoundException(Exception):
    pass


class ArgumentException(Exception):
    pass


class GPGEncryptCommand:
    def __init__(
        self,
        users: Iterable[Mapping[str, str]],
        secret_reader: SecretReader,
        command_data: GPGEncryptCommandData,
        gpg_encrypt_func: Callable,
    ):
        self._users = users
        self._secret_reader = secret_reader
        self._command_data = command_data
        self._gpg_encrypt_func = gpg_encrypt_func

    def _fetch_secret_content(self) -> str:
        if self._command_data.vault_secret_path:
            d = {"path": self._command_data.vault_secret_path}
            if self._command_data.vault_secret_version > 0:
                d["version"] = str(self._command_data.vault_secret_version)
            secret = self._secret_reader.read_all(d)
            return json.dumps(secret, sort_keys=True, indent=4)
        elif self._command_data.secret_file_path:
            with open(self._command_data.secret_file_path) as f:
                return f.read()
        else:
            raise ArgumentException(
                f"No argument given which defines how to fetch the secret {self._command_data}"
            )

    def _get_gpg_key(self) -> Optional[str]:
        try:
            return [
                user.get("public_gpg_key")
                for user in self._users
                if user.get("org_username") == self._command_data.target_user
            ][0]
        except IndexError:
            raise UserNotFoundException(
                f"Could not find public key for user {self._command_data.target_user}"
            )

    def _output(self, content: str):
        if not self._command_data.output:
            print(content)
            return
        with open(self._command_data.output, "w") as f:
            f.write(content)

    def execute(self):
        secret = self._fetch_secret_content()
        gpg_key = self._get_gpg_key()
        encrypted_content = self._gpg_encrypt_func(
            content=secret,
            public_gpg_key=gpg_key,
        )
        self._output(encrypted_content)

    @classmethod
    def create(
        cls,
        command_data: GPGEncryptCommandData,
        users: Optional[Iterable[Mapping[str, str]]] = None,
        secret_reader: Optional[SecretReader] = None,
        gpg_encrypt_func: Optional[Callable] = None,
    ) -> GPGEncryptCommand:
        cls_users = users if users else queries.get_users()
        cls_secret_reader = (
            secret_reader
            if secret_reader
            else SecretReader(settings=config.get_config())
        )
        gpg_casted: Callable = gpg.gpg_encrypt
        cls_gpg_func: Callable = gpg_encrypt_func if gpg_encrypt_func else gpg_casted
        return cls(
            command_data=command_data,
            users=cls_users,
            secret_reader=cls_secret_reader,
            gpg_encrypt_func=cls_gpg_func,
        )
