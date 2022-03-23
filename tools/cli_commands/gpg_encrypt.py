from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils import config
from reconcile import queries
from reconcile.utils import gpg

import json


@dataclass
class GPGEncryptCommandData:
    vault_secret_path: str = ""
    vault_secret_version: int = -1
    secret_file_path: str = ""
    output: str = ""
    target_user: str = ""


class UserException(Exception):
    pass


class ArgumentException(Exception):
    pass


class GPGEncryptCommand:
    def __init__(
        self,
        secret_reader: SecretReader,
        command_data: GPGEncryptCommandData,
    ):
        self._secret_reader = secret_reader
        self._command_data = command_data

    def _fetch_secret_content(self) -> str:
        vault_path = self._command_data.vault_secret_path
        vault_version = self._command_data.vault_secret_version
        file_path = self._command_data.secret_file_path
        if vault_path:
            d = {"path": vault_path}
            if vault_version > 0:
                d["version"] = str(vault_version)
            secret = self._secret_reader.read_all(d)
            return json.dumps(secret, sort_keys=True, indent=4)
        elif file_path:
            with open(file_path) as f:
                return f.read()
        else:
            raise ArgumentException(
                f"No argument given which defines how to fetch the secret {self._command_data}"
            )

    def _get_gpg_key(self) -> Optional[str]:
        target_user = self._command_data.target_user
        users = queries.get_users_by(
            refs=False,
            filter=queries.UserFilter(
                org_username=target_user,
            ),
        )
        if len(users) != 1:
            raise UserException(
                f"Expected to find exactly one user for '{target_user}', but found {len(users)}."
            )
        user = users[0]

        if "public_gpg_key" not in user:
            raise UserException(
                f"User '{target_user}' does not have an associated GPG key."
            )

        return user["public_gpg_key"]

    def _output(self, content: str):
        output = self._command_data.output
        if not output:
            print(content)
            return
        with open(output, "w") as f:
            f.write(content)

    def execute(self):
        secret = self._fetch_secret_content()
        gpg_key = self._get_gpg_key()
        encrypted_content = gpg.gpg_encrypt(
            content=secret,
            public_gpg_key=gpg_key,
        )
        self._output(encrypted_content)

    @classmethod
    def create(
        cls,
        command_data: GPGEncryptCommandData,
        secret_reader: Optional[SecretReader] = None,
    ) -> GPGEncryptCommand:
        cls_secret_reader = (
            secret_reader
            if secret_reader
            else SecretReader(settings=config.get_config())
        )

        return cls(
            command_data=command_data,
            secret_reader=cls_secret_reader,
        )
