import logging
import re

from reconcile.utils.vault import VaultClient, _VaultClient, SecretNotFound
from reconcile.gql_definitions.jenkins_configs import jenkins_configs
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigV1_JenkinsConfigV1,
)

from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.gql_definitions.vault_instances import vault_instances

from reconcile.utils import gql
from typing import List, cast, Optional

QONTRACT_INTEGRATION = "vault-replication"


class VaultInvalidPaths(Exception):
    pass


def deep_copy_versions(
    dry_run: bool,
    source_vault: _VaultClient,
    dest_vault: _VaultClient,
    current_dest_version: int,
    current_source_version: int,
    path: str,
):
    for version in range(current_dest_version + 1, current_source_version + 1):
        secret_dict = {"path": path, "version": version}
        secret, src_version = source_vault.read_all_with_version(secret_dict)
        write_dict = {"path": path, "data": secret}
        logging.info(["replicate_vault_secret", src_version, path])
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
            # v1 secrets don't have version
            secret, src_version = source_vault.read_all_with_version(secret_dict)
            write_dict = {"path": path, "data": secret}
            logging.info(["replicate_vault_secret", src_version, path])
            if not dry_run:
                dest_vault.write(write_dict)
        elif dest_version < version:
            deep_copy_versions(
                dry_run=dry_run,
                source_vault=source_vault,
                dest_vault=dest_vault,
                current_dest_version=dest_version,
                current_source_version=version,
                path=path,
            )
        else:
            logging.info(["replicate_vault_secret", dest_version, version, path])
    except SecretNotFound:
        logging.info(["replicate_vault_secret", "Secret not found", path])
        if version is None:
            if not dry_run:
                dest_vault.write(write_dict)
        deep_copy_versions(
            dry_run=dry_run,
            source_vault=source_vault,
            dest_vault=dest_vault,
            current_dest_version=0,
            current_source_version=version,
            path=path,
        )


def check_invalid_paths(
    path_list: List[str],
    policy_paths: Optional[List[str]],
) -> None:

    if policy_paths is not None:
        invalid_paths = list_invalid_paths(path_list, policy_paths)
        if invalid_paths:
            logging.error(["replicate_vault_secret", "Invalid paths", invalid_paths])
            raise VaultInvalidPaths


def list_invalid_paths(path_list: List[str], policy_paths: List[str]) -> List[str]:
    invalid_paths = []

    for path in path_list:
        if not policy_contains_path(path, policy_paths):
            invalid_paths.append(path)

    return invalid_paths


def policy_contains_path(path: str, policy_paths: List[str]) -> bool:
    return any(path in p_path for p_path in policy_paths)


def get_policy_paths(policy_name, instance_name) -> List[str]:
    query_data = vault_policies.query(query_func=gql.get_api().query)
    policy_paths = []

    if query_data.policy:
        for policy in query_data.policy:
            if policy.name == policy_name and policy.instance.name == instance_name:
                for line in policy.rules.split("\n"):
                    res = re.search(r"path \s*[\'\"](.+)[\'\"]", line)

                    if res is not None:
                        policy_paths.append(res.group(1))

    return policy_paths


def get_jenkins_secret_list(jenkins_instance: str) -> List[str]:
    secret_list = []
    query_data = jenkins_configs.query(query_func=gql.get_api().query)

    if query_data.jenkins_configs:
        for p in query_data.jenkins_configs:
            if (
                isinstance(p, JenkinsConfigV1_JenkinsConfigV1)
                and p.instance.name == jenkins_instance
                and p.config_path
            ):
                secret_paths = [
                    line
                    for line in p.config_path.content.split("\n")
                    if "secret-path" in line
                ]
                for line in secret_paths:
                    res = re.search(r"secret-path:\s*[\'\"](.+)[\'\"]", line)
                    if res is not None:
                        secret_list.append(res.group(1))

    return secret_list


def get_vault_credentials(vault_instance: VaultInstanceV1) -> dict[str, Optional[str]]:
    vault_creds = {}
    vault = cast(_VaultClient, VaultClient())

    vault_instance_auth = vault_instance.auth

    role_id = {
        "path": vault_instance_auth.role_id.path,
        "field": vault_instance_auth.role_id.field,
    }
    secret_id = {
        "path": vault_instance_auth.secret_id.path,
        "field": vault_instance_auth.secret_id.field,
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
            check_invalid_paths(path_list, policy_paths)
            for path in path_list:
                copy_vault_secret(dry_run, source_vault, dest_vault, path)


def run(dry_run: bool) -> None:

    query_data = vault_instances.query(query_func=gql.get_api().query)

    if query_data.vault_instances:
        for instance in query_data.vault_instances:
            if instance.replication:
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

                    replicate_paths(
                        dry_run=dry_run,
                        source_vault=source_vault,
                        dest_vault=dest_vault,
                        replications=replication,
                    )
