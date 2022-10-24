import logging
import re

from reconcile.utils.vault import VaultClient, _VaultClient, SecretNotFound
from reconcile.gql_definitions.jenkins_configs import jenkins_configs
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigV1,
)

from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.gql_definitions.vault_instances import vault_instances
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultReplicationV1,
    VaultInstanceV1,
)
from reconcile.gql_definitions.vault_policies.vault_policies import (
    VaultPolicyV1,
)

from reconcile.utils import gql

from typing import List, cast, Optional

QONTRACT_INTEGRATION = "vault-replication"


def deep_copy_versions(
    dry_run: bool,
    source_vault,
    dest_vault,
    current_dest_version,
    current_source_version,
    path,
):
    for version in range(current_dest_version + 1, current_source_version + 1):
        secret_dict = {"path": path, "version": version}
        copy_secret(dry_run, source_vault, dest_vault, path, version, secret_dict)


def copy_secret(
    dry_run: bool,
    source_vault: _VaultClient,
    dest_vault: _VaultClient,
    path: str,
    version: int,
    secret_dict: dict,
) -> None:
    secret, version = source_vault.read_all_with_version(secret_dict)
    write_dict = {"path": path, "data": secret}
    logging.info(["replicate_vault_secret", version, path])
    if not dry_run:
        dest_vault.write(write_dict)


def copy_vault_secret(
    dry_run: bool, source_vault: _VaultClient, dest_vault: _VaultClient, path: str
) -> None:

    secret_dict = {"path": path, "version": "LATEST"}
    _, version = source_vault.read_all_with_version(secret_dict)

    try:
        _, dest_version = dest_vault.read_all_with_version(secret_dict)
        if dest_version is None and version is None:
            # Secret is a v1 and does not return version
            copy_secret(dry_run, source_vault, dest_vault, path, 1, secret_dict)
        elif dest_version < version:
            deep_copy_versions(
                dry_run, source_vault, dest_vault, dest_version, version, path
            )
        else:
            logging.info(["replicate_vault_secret", dest_version, version, path])
    except SecretNotFound:
        logging.info(["replicate_vault_secret", "Secret not found", path])
        deep_copy_versions(dry_run, source_vault, dest_vault, 0, version, path)


def check_copy_secret_list(
    dry_run: bool,
    source_vault: _VaultClient,
    dest_vault: _VaultClient,
    path_list: List[str],
    policy_paths: Optional[List[str]],
) -> None:

    invalid_paths = []
    if policy_paths is not None:
        invalid_paths = list_invalid_paths(path_list, policy_paths)
    if invalid_paths:
        logging.error(["replicate_vault_secret", "Invalid paths", invalid_paths])
    else:
        for path in path_list:
            copy_vault_secret(dry_run, source_vault, dest_vault, path)


def list_invalid_paths(path_list: List[str], policy_paths: List[str]) -> List[str]:
    invalid_paths = []
    for path in path_list:
        if not policy_contais_path(path, policy_paths):
            invalid_paths.append(path)

    return invalid_paths


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


def get_jenkins_secret_list(jenkins_instance: str) -> List[str]:
    secret_list = []
    query_data = jenkins_configs.query(query_func=gql.get_api().query)

    for p in query_data.jenkins_configs:
        if (
            isinstance(p, JenkinsConfigV1)
            and p.instance.name == jenkins_instance
            and p.config_path
        ):
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
    vault_creds = {"server": "", "role_id": None, "secret_id": None}
    vault = cast(_VaultClient, VaultClient())

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


def replicate_paths(
    dry_run: bool, source_vault: _VaultClient, dest_vault: _VaultClient, replications
) -> None:
    for path in replications.paths:

        provider = path.provider

        if provider == "jenkins":
            if path.policy is not None:
                policy_paths = get_policy_paths(
                    path.policy.name,
                    path.policy.instance.name,
                )
            else:
                policy_paths = None

            path_list = get_jenkins_secret_list(path.jenkins_instance.name)
            check_copy_secret_list(
                dry_run, source_vault, dest_vault, path_list, policy_paths
            )


def run(dry_run: bool) -> None:

    query_data = vault_instances.query(query_func=gql.get_api().query)

    for instance in query_data.vault_instances:
        if isinstance(instance, VaultInstanceV1) and instance.replication:
            for replication in instance.replication:
                source_creds = get_vault_credentials(instance)
                dest_creds = get_vault_credentials(replication.vault_instance)

                source_vault = cast(
                    _VaultClient,
                    VaultClient(
                        server=source_creds["server"],
                        role_id=source_creds["role_id"],
                        secret_id=source_creds["secret_id"],
                    ),
                )
                dest_vault = cast(
                    _VaultClient,
                    VaultClient(
                        server=dest_creds["server"],
                        role_id=dest_creds["role_id"],
                        secret_id=dest_creds["secret_id"],
                    ),
                )

            replicate_paths(dry_run, source_vault, dest_vault, replication)
