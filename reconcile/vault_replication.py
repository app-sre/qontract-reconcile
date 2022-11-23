import logging
import re

from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
    SecretNotFound,
)
from reconcile.gql_definitions.jenkins_configs import jenkins_configs
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigV1_JenkinsConfigV1,
    JenkinsConfigsQueryData,
)

from reconcile.gql_definitions.vault_policies.vault_policies import (
    VaultPoliciesQueryData,
)

from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.gql_definitions.vault_instances import vault_instances
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultInstanceAuthApproleV1,
    VaultInstanceV1,
    VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    VaultReplicationConfigV1_VaultInstanceV1,
)

from reconcile.utils import gql
from typing import cast, Optional, Union, Iterable, Mapping

QONTRACT_INTEGRATION = "vault-replication"


class VaultInvalidPaths(Exception):
    pass


class VaultInvalidAuthMethod(Exception):
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
            secret, _ = source_vault.read_all_with_version(secret_dict)
            write_dict = {"path": path, "data": secret}
            logging.info(["replicate_vault_secret", path])
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
        # Handle v1 secrets where version is None and we don't need to deep sync.
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
    path_list: Iterable[str],
    policy_paths: Optional[Iterable[str]],
) -> None:

    if policy_paths is not None:
        invalid_paths = list_invalid_paths(path_list, policy_paths)
        if invalid_paths:
            logging.error(["replicate_vault_secret", "Invalid paths", invalid_paths])
            raise VaultInvalidPaths


def list_invalid_paths(
    path_list: Iterable[str], policy_paths: Iterable[str]
) -> Iterable[str]:
    invalid_paths = []

    for path in path_list:
        if not policy_contains_path(path, policy_paths):
            invalid_paths.append(path)

    return invalid_paths


def policy_contains_path(path: str, policy_paths: Iterable[str]) -> bool:
    return any(path in p_path for p_path in policy_paths)


def get_policy_paths(
    policy_name: str, instance_name: str, policy_query_data: VaultPoliciesQueryData
) -> Iterable[str]:
    # query_data = vault_policies.query(query_func=gql.get_api().query)
    policy_paths = []

    if policy_query_data.policy:
        for policy in policy_query_data.policy:
            if policy.name == policy_name and policy.instance.name == instance_name:
                for line in policy.rules.split("\n"):
                    res = re.search(r"path \s*[\'\"](.+)[\'\"]", line)

                    if res is not None:
                        policy_paths.append(res.group(1))

    return policy_paths


def get_jenkins_secret_list(
    jenkins_instance: str, query_data: JenkinsConfigsQueryData
) -> Iterable[str]:
    """Returns a list of secrets used in a jenkins instance

    The input secret is the name of a jenkins instance to filter
    the secrets:
    * jenkins_instance - Jenkins instance name
    """
    secret_list = []

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


def get_vault_credentials(
    vault_instance: Union[VaultInstanceV1, VaultReplicationConfigV1_VaultInstanceV1]
) -> Mapping[str, Optional[str]]:
    """Returns a dictionary with the credentials used to authenticate with Vault,
    retrieved from the values present on AppInterface.

    The input is a VaultInstanceV1 object, that contains secret references to be retreived
    from vault. The output is a dictionary with the credentials used to authenticate with
    Vault.
    * vault_instance - VaultInstanceV1 object from AppInterface Data.
    """
    vault_creds = {}
    vault = cast(_VaultClient, VaultClient())

    if not isinstance(
        vault_instance.auth, VaultInstanceAuthApproleV1
    ) and not isinstance(
        vault_instance.auth,
        VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    ):
        raise VaultInvalidAuthMethod

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
                vault_query_data = vault_policies.query(query_func=gql.get_api().query)
                policy_paths = get_policy_paths(
                    path.policy.name,
                    path.policy.instance.name,
                    vault_query_data,
                )
            else:
                policy_paths = None

            jenkins_query_data = jenkins_configs.query(query_func=gql.get_api().query)
            path_list = get_jenkins_secret_list(
                path.jenkins_instance.name, jenkins_query_data
            )
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

                    # Private class _VaultClient is used because the public class is
                    # defined as a singleton, and we need to create multiple instances
                    # as the source vault is different than the replication.
                    source_vault = _VaultClient(
                        server=source_creds["server"],
                        role_id=source_creds["role_id"],
                        secret_id=source_creds["secret_id"],
                    )
                    dest_vault = _VaultClient(
                        server=dest_creds["server"],
                        role_id=dest_creds["role_id"],
                        secret_id=dest_creds["secret_id"],
                    )

                    replicate_paths(
                        dry_run=dry_run,
                        source_vault=source_vault,
                        dest_vault=dest_vault,
                        replications=replication,
                    )
