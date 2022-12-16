import logging
import re
from collections.abc import Iterable
from typing import (
    Optional,
    Union,
    cast,
)

from reconcile.gql_definitions.jenkins_configs import jenkins_configs
from reconcile.gql_definitions.jenkins_configs.jenkins_configs import (
    JenkinsConfigsQueryData,
    JenkinsConfigV1_JenkinsConfigV1,
)
from reconcile.gql_definitions.vault_instances import vault_instances
from reconcile.gql_definitions.vault_instances.vault_instances import (
    VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1,
    VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    VaultReplicationConfigV1,
    VaultReplicationConfigV1_VaultInstanceAuthV1,
    VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    VaultReplicationJenkinsV1,
)
from reconcile.gql_definitions.vault_policies import vault_policies
from reconcile.gql_definitions.vault_policies.vault_policies import (
    VaultPoliciesQueryData,
)
from reconcile.utils import gql
from reconcile.utils.vault import (
    SecretAccessForbidden,
    SecretNotFound,
    SecretVersionNotFound,
    VaultClient,
    _VaultClient,
)

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
) -> None:
    """Copies all versions of a V2 secret from the source vault to the destination vault, starting
    on latest version present on the destination vault"""
    for version in range(current_dest_version + 1, current_source_version + 1):
        secret_dict = {"path": path, "version": version}

        try:
            secret, src_version = source_vault.read_all_with_version(secret_dict)
        except SecretNotFound:
            # Handle the case where the difference between the source and destination
            # versions is greater than the number of versions in the source vault.
            # By default the secret engines store up to 10 versions of a secret.
            # If current destination version is 5 and current source version is 17
            # we need to create dummy versions 6 and 7 in the destination vault.
            # to have matching versions in both vaults.
            write_dummy_versions(
                dry_run=dry_run,
                dest_vault=dest_vault,
                secret_version=version,
                path=path,
            )
            continue

        write_dict = {"path": path, "data": secret}
        logging.info(["replicate_vault_secret", src_version, path])
        if not dry_run:
            # Using force=True to write the secret to force the vault client even
            # if the data is the same as the previous version. This happens in
            # some secrets even tho the library does not create it
            dest_vault.write(secret=write_dict, decode_base64=False, force=True)


def write_dummy_versions(
    dry_run: bool,
    dest_vault: _VaultClient,
    secret_version: int,
    path: str,
) -> None:
    """Writes dummy data to dest_vault to generate missing versions when the difference
    between the source and destination versions is greater than the number of versions
    that a secret engine stores"""

    write_dict = {"path": path, "data": {"dummy": "data"}}
    logging.info(
        ["replicate_vault_secret", "generate_dummy_data", secret_version, path]
    )
    if not dry_run:
        # Using force=True to write the dummy data to force the vault client
        # to write the version even if the data is the same as the previous version.
        dest_vault.write(secret=write_dict, decode_base64=False, force=True)


def copy_vault_secret(
    dry_run: bool, source_vault: _VaultClient, dest_vault: _VaultClient, path: str
) -> None:
    """Copies a secret from the source vault to the destination vault"""
    secret_dict = {"path": path, "version": "LATEST"}

    try:
        source_data, version = source_vault.read_all_with_version(secret_dict)
    except SecretAccessForbidden:
        # Raise exception if we can't read the secret from the source vault.
        # This is likely to be related to the approle permissions.
        raise SecretAccessForbidden("Cannot read secret from source vault")

    try:
        dest_data, dest_version = dest_vault.read_all_with_version(secret_dict)
        if dest_version is None and version is None:
            # v1 secrets don't have version
            if source_data == dest_data:
                # If the secret is the same in both vaults, we don't need
                # to copy it again
                return

            secret, _ = source_vault.read_all_with_version(secret_dict)
            write_dict = {"path": path, "data": secret}
            logging.info(["replicate_vault_secret", path])
            if not dry_run:
                # Using force=True to write the secret to force the vault client even
                # if the data is the same as the previous version. This happens in
                # some secrets even tho the library does not create it
                dest_vault.write(secret=write_dict, decode_base64=False, force=True)
        elif dest_version < version:
            deep_copy_versions(
                dry_run=dry_run,
                source_vault=source_vault,
                dest_vault=dest_vault,
                current_dest_version=dest_version,
                current_source_version=version,
                path=path,
            )
    except (SecretVersionNotFound, SecretNotFound):
        logging.info(["replicate_vault_secret", "Secret not found", path])
        # Handle v1 secrets where version is None and we don't need to deep sync.
        if version is None:
            logging.info(["replicate_vault_secret", path])
            if not dry_run:
                secret, _ = source_vault.read_all_with_version(secret_dict)
                write_dict = {"path": path, "data": secret}
                dest_vault.write(secret=write_dict, decode_base64=False, force=True)
        else:
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
    """Checks if the paths to be replicated are present in the policy used to limit the secrets
    that are going to be replicated."""

    if policy_paths is not None:
        invalid_paths = list_invalid_paths(path_list, policy_paths)
        if invalid_paths:
            # Exit if we have paths not present in the policy that needs to be replicated
            # this is to prevent to replicate secrets that are not allowed.
            logging.error(["replicate_vault_secret", "Invalid paths", invalid_paths])
            raise VaultInvalidPaths


def list_invalid_paths(
    path_list: Iterable[str], policy_paths: Iterable[str]
) -> list[str]:
    """Returns a list of paths that are listed to be copied are not present in the policy
    to fail the integration if we are trying to copy secrets that are not allowed."""

    invalid_paths = []

    for path in path_list:
        if not _policy_contains_path(path, policy_paths):
            invalid_paths.append(path)

    return invalid_paths


def _policy_contains_path(path: str, policy_paths: Iterable[str]) -> bool:
    return any(path in p_path for p_path in policy_paths)


def get_policy_paths(
    policy_name: str, instance_name: str, policy_query_data: VaultPoliciesQueryData
) -> list[str]:
    """Get all paths that are allowed to be copied from the given policy"""
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
    vault_instance: _VaultClient,
    jenkins_instance: str,
    query_data: JenkinsConfigsQueryData,
) -> list[str]:
    """Returns a list of secrets used in a jenkins instance"""
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
                        secret_path = res.group(1)
                        if "{" in secret_path:
                            start, _ = _get_start_end_secret(secret_path)
                            vault_list = vault_instance.list_all(start)
                            template_expasion_list = get_secrets_from_templated_path(
                                path=secret_path,
                                vault_list=vault_list,
                            )
                            secret_list.extend(template_expasion_list)
                        else:
                            secret_list.append(secret_path)

    return secret_list


def get_vault_credentials(
    vault_auth: Union[
        VaultReplicationConfigV1_VaultInstanceAuthV1,
        VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1,
    ],
    vault_address: str,
) -> dict[str, Optional[str]]:
    """Returns a dictionary with the credentials used to authenticate with Vault,
    retrieved from the values present on AppInterface and comming from Vault itself."""
    vault_creds = {}
    vault = cast(_VaultClient, VaultClient())

    if not isinstance(
        vault_auth,
        VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    ) and not isinstance(
        vault_auth,
        VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
    ):
        # Exit if the auth method is not approle as is the only one supported
        raise VaultInvalidAuthMethod

    role_id = {
        "path": vault_auth.role_id.path,
        "field": vault_auth.role_id.field,
    }
    secret_id = {
        "path": vault_auth.secret_id.path,
        "field": vault_auth.secret_id.field,
    }

    vault_creds["role_id"] = vault.read(role_id)
    vault_creds["secret_id"] = vault.read(secret_id)
    vault_creds["server"] = vault_address

    return vault_creds


def replicate_paths(
    dry_run: bool,
    source_vault: _VaultClient,
    dest_vault: _VaultClient,
    replications: VaultReplicationConfigV1,
) -> None:
    """For each path present in the definition of the vault instance, replicate
    the secrets from the source vault to the destination vault"""

    if replications.paths is None:
        return

    for path in replications.paths:

        if isinstance(path, VaultReplicationJenkinsV1):
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
                source_vault, path.jenkins_instance.name, jenkins_query_data
            )
            check_invalid_paths(path_list, policy_paths)
            for vault_path in path_list:
                copy_vault_secret(dry_run, source_vault, dest_vault, vault_path)


def _get_start_end_secret(path: str) -> tuple[str, str]:

    start = path[0 : path.index("{")]
    if start[-1] != "/":
        start = start.rsplit("/", 1)[0] + "/"
    try:
        end = path[path[path.rindex("}") : :].index("/") + path.rindex("}") : :]
    except ValueError:
        end = ""

    return start, end


def get_secrets_from_templated_path(path: str, vault_list: Iterable[str]) -> list[str]:
    """Returns a list of secrets that match with the templated path expansion."""

    secret_list = []
    non_template_slices = []
    path_slices = path.split("/")
    for s in path_slices:
        if "{" in s and "}" in s:
            template = s
        else:
            non_template_slices.append(s)

    cap_groups = re.search(r"(.*)(\{.*\})(.*)", template)
    if cap_groups is not None:
        prefix = cap_groups.group(1)
        suffix = cap_groups.group(3)
    else:
        # Exit if the path is not a valid formatted template on the secret path
        raise VaultInvalidPaths

    secret_start, secret_end = _get_start_end_secret(path)

    for secret in vault_list:
        if any(item for item in non_template_slices if item not in secret.split("/")):
            # If there are any part of the orignal templated path is not present
            # in the secret from vault, we don't want to copy it
            continue
        if not secret.startswith(secret_start) or not secret.endswith(secret_end):
            continue
        if prefix not in secret or suffix not in secret:
            continue

        secret_list.append(secret)

    return secret_list


def run(dry_run: bool) -> None:

    query_data = vault_instances.query(query_func=gql.get_api().query)

    if query_data.vault_instances:
        for instance in query_data.vault_instances:
            if instance.replication:
                for replication in instance.replication:
                    source_creds = get_vault_credentials(
                        replication.source_auth, instance.address
                    )
                    dest_creds = get_vault_credentials(
                        replication.dest_auth, replication.vault_instance.address
                    )

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
