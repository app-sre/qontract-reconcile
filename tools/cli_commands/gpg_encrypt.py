from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from reconcile import queries
from reconcile.utils import (
    config,
    gpg,
)
from reconcile.utils.oc import OC_Map
from reconcile.utils.secret_reader import SecretReader


@dataclass
class GPGEncryptCommandData:
    vault_secret_path: str = ""
    vault_secret_version: int = -1
    openshift_path: str = ""
    secret_file_path: str = ""
    output: str = ""
    target_user: str = ""


class UserException(Exception):
    pass


class ArgumentException(Exception):
    pass


class OpenshiftException(Exception):
    pass


class GPGEncryptCommand:
    def __init__(
        self,
        secret_reader: SecretReader,
        command_data: GPGEncryptCommandData,
    ):
        self._secret_reader = secret_reader
        self._command_data = command_data

    @staticmethod
    def _format(data: Mapping[str, str]) -> str:
        return json.dumps(data, sort_keys=True, indent=4)

    def _fetch_oc_secret(self) -> str:
        parts = self._command_data.openshift_path.split("/")
        if len(parts) != 3:
            raise ArgumentException(
                f"Wrong format! --openshift-path must be of format {{cluster}}/{{namespace}}/{{secret}}. Got {self._command_data.openshift_path}"
            )
        cluster_name, namespace, secret = parts
        clusters = queries.get_clusters_by(
            filter=queries.ClusterFilter(
                name=cluster_name,
            )
        )

        if not clusters:
            raise ArgumentException(f"No cluster found with name '{cluster_name}'")

        settings = queries.get_app_interface_settings()
        data = {}

        try:
            oc_map = OC_Map(
                clusters=clusters,
                integration="qontract-cli",
                settings=settings,
                use_jump_host=True,
                thread_pool_size=1,
                init_projects=False,
            )
            oc = oc_map.get(cluster_name)
            data = oc.get(namespace, "Secret", name=secret, allow_not_found=False)[
                "data"
            ]
        except Exception as e:
            raise OpenshiftException(
                f"Could not fetch secret from Openshift cluster {cluster_name}"
            ) from e

        return GPGEncryptCommand._format(data)

    def _fetch_vault_secret(self) -> str:
        vault_path = self._command_data.vault_secret_path
        vault_version = self._command_data.vault_secret_version
        d = {"path": vault_path}
        if vault_version > 0:
            d["version"] = str(vault_version)
        secret = self._secret_reader.read_all(d)
        return GPGEncryptCommand._format(secret)

    def _fetch_local_file_secret(self) -> str:
        with open(self._command_data.secret_file_path, encoding="locale") as f:
            return f.read()

    def _fetch_secret(self) -> str:
        if self._command_data.vault_secret_path:
            return self._fetch_vault_secret()
        if self._command_data.secret_file_path:
            return self._fetch_local_file_secret()
        if self._command_data.openshift_path:
            return self._fetch_oc_secret()
        raise ArgumentException(
            f"No argument given which defines how to fetch the secret {self._command_data}"
        )

    def _get_gpg_key(self) -> str | None:
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

    def _output(self, content: str) -> None:
        output = self._command_data.output
        if not output:
            print(content)
            return
        with open(output, "w", encoding="locale") as f:
            f.write(content)

    def execute(self) -> None:
        secret = self._fetch_secret()
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
        secret_reader: SecretReader | None = None,
    ) -> GPGEncryptCommand:
        cls_secret_reader = secret_reader or SecretReader(settings=config.get_config())

        return cls(
            command_data=command_data,
            secret_reader=cls_secret_reader,
        )
