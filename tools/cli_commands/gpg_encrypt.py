from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils import config
from reconcile import queries
from reconcile.utils import gpg

import json


@dataclass
class GPGEncryptCommandData:
    vault_secret_path: str
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
            secret = self._secret_reader.read_all(
                {
                    "path": self._command_data.vault_secret_path,
                }
            )
            return json.dumps(secret, sort_keys=True, indent=4)
        elif self._command_data.secret_file_path:
            with open(self._command_data.secret_file_path) as f:
                return f.read()
        else:
            raise ArgumentException(
                f"No argument given which defines how to fetch the secret {self._command_data}"
            )

    def _get_gpg_key(self) -> str:
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
        users: Iterable[Mapping[str, str]] = None,
        secret_reader: SecretReader = None,
        gpg_encrypt_func: Callable = None,
    ) -> GPGEncryptCommand:
        if not users:
            users = queries.get_users()
        if not secret_reader:
            secret_reader = SecretReader(
                settings=config.get_config(),
            )
        if not gpg_encrypt_func:
            gpg_encrypt_func = gpg.gpg_encrypt
        return cls(
            command_data=command_data,
            users=users,
            secret_reader=secret_reader,
            gpg_encrypt_func=gpg_encrypt_func,
        )
