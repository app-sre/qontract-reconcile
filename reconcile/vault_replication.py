import logging
import re

from reconcile.utils.vault import VaultClient, SecretNotFound
from reconcile.gql_definitions.jenkins_configs import jenkins_configs

from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.gql_definitions.vault_instances import vault_instances
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultReplicationV1,
)
from reconcile.gql_definitions.vault_policies.vault_policies import (
    VaultPolicyV1,
)

from reconcile.utils import gql

from typing import List

QONTRACT_INTEGRATION = "vault-replication"


def copy_vault_secret(
    dry_run: bool, source_vault: VaultClient, dest_vault: VaultClient, path: str
) -> None:

    secret_dict = {"path": path, "version": "LATEST"}
    secrets, version = source_vault.read_all_version(secret_dict)
    for secret in secrets:
        write_dict = {"path": path, "data": secret}
        try:
            _, dest_version = dest_vault.read_all(secret_dict)
            if dest_version < version:
                logging.info(
                    [
                        "replicate_vault_secret",
                        "Secret found, new version",
                        version,
                        path,
                    ]
                )
                if not dry_run:
                    dest_vault.write(write_dict)
            else:
                logging.info(["replicate_vault_secret", dest_version, version, secret])
        except SecretNotFound:
            logging.info(["replicate_vault_secret", "Secret not found", path])
            if not dry_run:
                dest_vault.write(write_dict)


def copy_vault_secrets(
    dry_run: bool,
    source_vault: VaultClient,
    dest_vault: VaultClient,
    path_list: List[str],
    policy_paths: List[str],
) -> None:

    for path in path_list:
        if is_valid_path(path, policy_paths):
            logging.info(["replicate_vault_secret", path])
            copy_vault_secret(dry_run, source_vault, dest_vault, path)


def is_valid_path(path: str, policy_paths: List[str]) -> bool:
    if not policy_contais_path(path, policy_paths):
        logging.error(["replicate_vault_secret", "Invalid path", path])
        return False
    else:
        return True


def policy_contais_path(path: str, policy_paths: List[str]) -> bool:
    if policy_paths is None:
        return True
    else:
        return any(path in p_path for p_path in policy_paths)


def get_policy_paths(policy_name, instance_name) -> List[str]:
    query_data = vault_policies.query(query_func=gql.get_api().query)
    policy_paths = []

    for policy in query_data.policy:
        if (
            isinstance(policy, VaultPolicyV1)
            and policy.name == policy_name
            and policy.instance.name == instance_name
        ):
            for line in policy.rules.split("\n"):
                res = re.search(r"path \s*[\'\"](.*)[\'\"]", line)

                if res is not None:
                    policy_paths.append(res.group(1))

    return policy_paths


def get_jenkins_secret_list() -> List[str]:
    secret_list = []
    query_data = jenkins_configs.query(query_func=gql.get_api().query)

    for p in query_data.jenkins_configs:
        if p.config_path and p.config_path.content != "":
            secret_paths = [
                line
                for line in p.config_path.content.split("\n")
                if "secret-path" in line
            ]
            for line in secret_paths:
                res = re.search(r"secret-path:\s*[\'\"](.*)[\'\"]", line).group(1)
                secret_list.append(res)

    return secret_list


def get_vault_credentials(vault_instance: vault_instances.VaultInstanceV1):
    vault_creds = {"server": None, "role_id": None, "secret_id": None}
    vault = VaultClient()

    if isinstance(vault_instance, VaultReplicationV1):
        vault_instance = vault_instance.instance

    role_id = {
        "path": vault_instance.auth.role_id.path,
        "field": vault_instance.auth.role_id.field,
    }
    secret_id = {
        "path": vault_instance.auth.secret_id.path,
        "field": vault_instance.auth.secret_id.field,
    }

    vault_creds["role_id"] = vault.read(role_id)
    vault_creds["secret_id"] = vault.read(secret_id)
    vault_creds["server"] = vault_instance.address

    return vault_creds


def run(dry_run: bool) -> None:

    query_data = vault_instances.query(query_func=gql.get_api().query)

    for instance in query_data.vault_instances:
        if instance.replication is not None:
            for replication in instance.replication:
                source_creds = get_vault_credentials(instance)
                dest_creds = get_vault_credentials(instance.replication[0])

                source_vault = VaultClient(
                    server=source_creds["server"],
                    role_id=source_creds["role_id"],
                    secret_id=source_creds["secret_id"],
                )
                dest_vault = VaultClient(
                    server=dest_creds["server"],
                    role_id=dest_creds["role_id"],
                    secret_id=dest_creds["secret_id"],
                )

                provider = replication.provider

                if provider == "jenkins":
                    if replication.policy is not None:
                        policy_paths = get_policy_paths(
                            replication.policy.name,
                            replication.policy.instance.name,
                        )
                    else:
                        policy_paths = None

                    path_list = get_jenkins_secret_list()
                    copy_vault_secrets(
                        dry_run, source_vault, dest_vault, path_list, policy_paths
                    )
