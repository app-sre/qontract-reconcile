import logging
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Mapping,
    Sequence,
)
from dataclasses import asdict
from typing import (
    Any,
    TypedDict,
    cast,
)

from deepdiff import DeepHash
from sretoolbox.utils import (
    retry,
    threaded,
)

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.aws_iam_keys import run as disable_keys
from reconcile.gql_definitions.terraform_resources.terraform_resources_namespaces import (
    NamespaceV1,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.terraform_namespaces import get_namespaces
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpecInventory,
)
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
    managed_external_resources,
    publish_metrics,
)
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.oc_map import (
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.ocm import OCMMap
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "terraform_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 5, 5)
QONTRACT_TF_PREFIX = "qrtf"


def get_tf_namespaces(
    account_names: Iterable[str] | None = None,
) -> list[NamespaceV1]:
    namespaces = get_namespaces()
    return filter_tf_namespaces(namespaces, account_names)


def populate_oc_resources(
    spec: ob.CurrentStateSpec,
    ri: ResourceInventory,
    account_names: Iterable[str] | None,
) -> None:
    if spec.oc is None:
        return
    logging.debug(
        "[populate_oc_resources] cluster: "
        + spec.cluster
        + " namespace: "
        + spec.namespace
        + " resource: "
        + spec.kind
    )

    try:
        for item in spec.oc.get_items(spec.kind, namespace=spec.namespace):
            openshift_resource = OR(
                item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )
            if account_names:
                caller = openshift_resource.caller
                if caller and caller not in account_names:
                    continue

            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.kind,
                openshift_resource.name,
                openshift_resource,
            )
    except StatusCodeError as e:
        ri.register_error(cluster=spec.cluster)
        msg = "cluster: {},"
        msg += "namespace: {},"
        msg += "resource: {},"
        msg += "exception: {}"
        msg = msg.format(spec.cluster, spec.namespace, spec.kind, str(e))
        logging.error(msg)


def fetch_current_state(
    namespaces: Iterable[NamespaceV1],
    thread_pool_size: int,
    internal: bool | None,
    use_jump_host: bool,
    account_names: Iterable[str] | None,
    secret_reader: SecretReaderBase,
) -> tuple[ResourceInventory, OCMap]:
    ri = ResourceInventory()
    oc_map = init_oc_map_from_namespaces(
        namespaces=namespaces,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    namespaces_dicts = [ns.dict(by_alias=True) for ns in namespaces]
    state_specs = ob.init_specs_to_fetch(
        ri, oc_map, namespaces=namespaces_dicts, override_managed_types=["Secret"]
    )
    current_state_specs: list[ob.CurrentStateSpec] = [
        s for s in state_specs if isinstance(s, ob.CurrentStateSpec)
    ]
    threaded.run(
        populate_oc_resources,
        current_state_specs,
        thread_pool_size,
        ri=ri,
        account_names=account_names,
    )

    return ri, oc_map


def init_working_dirs(
    accounts: list[dict[str, Any]],
    thread_pool_size: int,
    settings: Mapping[str, Any] | None = None,
) -> tuple[Terrascript, dict[str, str]]:
    ts = Terrascript(
        QONTRACT_INTEGRATION,
        QONTRACT_TF_PREFIX,
        thread_pool_size,
        accounts,
        settings=settings,
    )
    working_dirs = ts.dump()
    return ts, working_dirs


def filter_accounts_by_name(
    accounts: Iterable[dict[str, Any]], names: Iterable[str]
) -> list[dict[str, Any]]:
    return [ac for ac in accounts if ac["name"] in names]


def exclude_accounts_by_name(
    accounts: Iterable[dict[str, Any]], names: Iterable[str]
) -> list[dict[str, Any]]:
    return [ac for ac in accounts if ac["name"] not in names]


def validate_account_names(
    accounts: Collection[Mapping[str, Any]], names: Collection[str]
) -> None:
    if missing_names := set(names) - {a["name"] for a in accounts}:
        raise ValueError(
            f"Accounts {missing_names} were provided as arguments, but not found in app-interface. Check your input for typos or for missing AWS account definitions."
        )


def get_aws_accounts(
    dry_run: bool,
    include_accounts: Collection[str] | None,
    exclude_accounts: Collection[str] | None,
) -> list[dict[str, Any]]:
    if exclude_accounts and not dry_run:
        message = "--exclude-accounts is only supported in dry-run mode"
        logging.error(message)
        raise ExcludeAccountsAndDryRunException(message)

    if (exclude_accounts and include_accounts) and any(
        a in exclude_accounts for a in include_accounts
    ):
        message = "Using --exclude-accounts and --account-name with the same account is not allowed"
        logging.error(message)
        raise ExcludeAccountsAndAccountNameException(message)

    # If we are not running in dry run we don't want to run with more than one account
    if include_accounts and len(include_accounts) > 1 and not dry_run:
        message = "Running with multiple accounts is only supported in dry-run mode"
        logging.error(message)
        raise MultipleAccountNamesInDryRunException(message)

    accounts = queries.get_aws_accounts(terraform_state=True)

    if exclude_accounts:
        validate_account_names(accounts, exclude_accounts)
        filtered_accounts = exclude_accounts_by_name(accounts, exclude_accounts)
        if not filtered_accounts:
            raise ValueError("You have excluded all aws accounts, verify your input")
        return filtered_accounts

    if include_accounts:
        validate_account_names(accounts, include_accounts)
        return filter_accounts_by_name(accounts, include_accounts)

    return accounts


def setup(
    accounts: list[dict[str, Any]],
    account_names: set[str],
    tf_namespaces: list[NamespaceV1],
    print_to_file: str | None,
    thread_pool_size: int,
) -> tuple[Terraform, TerrascriptClient, SecretReaderBase]:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    settings = queries.get_app_interface_settings()
    # initialize terrascript (scripting engine to generate terraform manifests)
    ts, working_dirs = init_working_dirs(accounts, thread_pool_size, settings=settings)

    # initialize terraform client
    # it is used to plan and apply according to the output of terrascript
    aws_api = AWSApi(1, accounts, settings=settings, init_users=False)
    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
    )
    clusters = [c for c in queries.get_clusters() if c.get("ocm") is not None]
    if clusters:
        ocm_map = OCMMap(
            clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
        )
    else:
        ocm_map = None
    tf_namespaces_dicts = [ns.dict(by_alias=True) for ns in tf_namespaces]
    ts.init_populate_specs(tf_namespaces_dicts, account_names)
    tf.populate_terraform_output_secrets(
        resource_specs=ts.resource_spec_inventory, init_rds_replica_source=True
    )
    ts.populate_resources(ocm_map=ocm_map)
    ts.dump(print_to_file, existing_dirs=working_dirs)

    return tf, ts, secret_reader


def filter_tf_namespaces(
    namespaces: Iterable[NamespaceV1], account_names: Iterable[str] | None
) -> list[NamespaceV1]:
    tf_namespaces = []
    for namespace_info in namespaces:
        if ob.is_namespace_deleted(namespace_info.dict(by_alias=True)):
            continue
        if not managed_external_resources(namespace_info.dict(by_alias=True)):
            continue

        if not account_names:
            tf_namespaces.append(namespace_info)
            continue

        specs = get_external_resource_specs(namespace_info.dict(by_alias=True))
        if not specs:
            tf_namespaces.append(namespace_info)
            continue

        for spec in specs:
            if spec.provisioner_name in account_names:
                tf_namespaces.append(namespace_info)
                break

    return tf_namespaces


@retry()
def write_outputs_to_vault(
    vault_path: str, resource_specs: ExternalResourceSpecInventory
) -> None:
    integration_name = QONTRACT_INTEGRATION.replace("_", "-")
    vault_client = cast(_VaultClient, VaultClient())
    for spec in resource_specs.values():
        # a secret can be empty if the terraform-integration is not enabled on the cluster
        # the resource is defined on - lets skip vault writes for those right now and
        # give this more thought - e.g. not processing such specs at all when the integration
        # is disabled
        if spec.secret:
            secret_path = f"{vault_path}/{integration_name}/{spec.cluster_name}/{spec.namespace_name}/{spec.output_resource_name}"
            # vault only stores strings as values - by converting to str upfront, we can compare current to desired
            stringified_secret = {k: str(v) for k, v in spec.secret.items()}
            desired_secret = {"path": secret_path, "data": stringified_secret}
            vault_client.write(desired_secret, decode_base64=False)


def populate_desired_state(
    ri: ResourceInventory, resource_specs: ExternalResourceSpecInventory
) -> None:
    for spec in resource_specs.values():
        if ri.is_cluster_present(spec.cluster_name):
            oc_resource = spec.build_oc_secret(
                QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )
            ri.add_desired(
                cluster=spec.cluster_name,
                namespace=spec.namespace_name,
                resource_type=oc_resource.kind,
                name=spec.output_resource_name,
                value=oc_resource,
                privileged=spec.namespace.get("clusterAdmin") or False,
            )


class ExcludeAccountsAndDryRunException(Exception):
    pass


class ExcludeAccountsAndAccountNameException(Exception):
    pass


class MultipleAccountNamesInDryRunException(Exception):
    pass


class CacheSource(TypedDict):
    terraform_configurations: dict[str, str]
    resource_spec_inventory: ExternalResourceSpecInventory


@defer
def run(
    dry_run: bool,
    print_to_file: str | None = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    light: bool = False,
    vault_output_path: str = "",
    account_name: Sequence[str] | None = None,
    exclude_accounts: Sequence[str] | None = None,
    enable_extended_early_exit: bool = False,
    extended_early_exit_cache_ttl_seconds: int = 3600,
    log_cached_log_output: bool = False,
    defer: Callable | None = None,
) -> None:
    # account_name is a tuple of account names for more detail go to
    # https://click.palletsprojects.com/en/8.1.x/options/#multiple-options
    accounts = get_aws_accounts(dry_run, account_name, exclude_accounts)
    account_names = {a["name"] for a in accounts}
    tf_namespaces = get_tf_namespaces(account_names)
    if not tf_namespaces:
        logging.warning(
            "No terraform namespaces found, consider disabling this integration, account names: "
            f"{', '.join(account_names)}"
        )

    tf, ts, secret_reader = setup(
        accounts,
        account_names,
        tf_namespaces,
        print_to_file,
        thread_pool_size,
    )
    if defer:
        defer(tf.cleanup)

    publish_metrics(ts.resource_spec_inventory, QONTRACT_INTEGRATION)

    if print_to_file:
        return

    runner_params: RunnerParams = {
        "accounts": accounts,
        "account_names": account_names,
        "tf_namespaces": tf_namespaces,
        "tf": tf,
        "ts": ts,
        "secret_reader": secret_reader,
        "dry_run": dry_run,
        "enable_deletion": enable_deletion,
        "thread_pool_size": thread_pool_size,
        "internal": internal,
        "use_jump_host": use_jump_host,
        "light": light,
        "vault_output_path": vault_output_path,
        "defer": defer,
    }

    if enable_extended_early_exit and get_feature_toggle_state(
        "terraform-resources-extended-early-exit",
        default=False,
    ):
        cache_source = CacheSource(
            terraform_configurations=ts.terraform_configurations(),
            resource_spec_inventory=ts.resource_spec_inventory,
        )
        extended_early_exit_run(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_source=cache_source,
            shard="_".join(account_name) if account_name else "",
            ttl_seconds=extended_early_exit_cache_ttl_seconds,
            logger=logging.getLogger(),
            runner=runner,
            runner_params=runner_params,
            secret_reader=secret_reader,
            log_cached_log_output=log_cached_log_output,
        )
    else:
        runner(**runner_params)


class RunnerParams(TypedDict):
    accounts: list[dict[str, Any]]
    account_names: set[str]
    tf_namespaces: list[NamespaceV1]
    tf: Terraform
    ts: Terrascript
    secret_reader: SecretReaderBase
    dry_run: bool
    enable_deletion: bool
    thread_pool_size: int
    internal: bool | None
    use_jump_host: bool
    light: bool
    vault_output_path: str
    defer: Callable | None


def runner(
    accounts: list[dict[str, Any]],
    account_names: set[str],
    tf_namespaces: list[NamespaceV1],
    tf: Terraform,
    ts: Terrascript,
    secret_reader: SecretReaderBase,
    dry_run: bool,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    light: bool = False,
    vault_output_path: str = "",
    defer: Callable | None = None,
) -> ExtendedEarlyExitRunnerResult:
    if not light:
        disabled_deletions_detected, err = tf.plan(enable_deletion)
        if err:
            raise RuntimeError("Terraform plan has errors")
        if disabled_deletions_detected:
            raise RuntimeError("Terraform plan has disabled deletions detected")

    if dry_run:
        return ExtendedEarlyExitRunnerResult(
            payload=ts.terraform_configurations(),
            applied_count=0,
        )

    acc_name = accounts[0]["name"] if accounts else None
    if not light and tf.should_apply():
        err = tf.apply()
        if err:
            raise RuntimeError("Terraform apply has errors")

        if defer:
            defer(
                disable_keys,
                dry_run,
                thread_pool_size,
                disable_service_account_keys=True,
                account_name=acc_name,
            )

    # refresh output data after terraform apply
    tf.populate_terraform_output_secrets(
        resource_specs=ts.resource_spec_inventory, init_rds_replica_source=True
    )

    ri, oc_map = fetch_current_state(
        tf_namespaces,
        thread_pool_size,
        internal,
        use_jump_host,
        account_names,
        secret_reader=secret_reader,
    )
    if defer:
        defer(oc_map.cleanup)
    # populate the resource inventory with latest output data
    populate_desired_state(ri, ts.resource_spec_inventory)

    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    actions = ob.realize_data(
        dry_run,
        oc_map,
        ri,
        thread_pool_size,
        caller=acc_name,
    )

    if actions and vault_output_path:
        write_outputs_to_vault(vault_output_path, ts.resource_spec_inventory)

    if ri.has_error_registered():
        raise RuntimeError("Resource inventory has errors registered")

    return ExtendedEarlyExitRunnerResult(
        payload=ts.terraform_configurations(),
        applied_count=tf.apply_count + len(actions),
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    state_for_accounts = {
        account["name"]: {
            "meta": account,
            "specs": {},
        }
        for account in queries.get_aws_accounts(terraform_state=True)
    }
    for ns_info in get_tf_namespaces():
        for spec in get_external_resource_specs(
            ns_info.dict(by_alias=True), provision_provider=PROVIDER_AWS
        ):
            resource_paths = [
                spec.resource.get("defaults"),
                spec.resource.get("parameter_group"),
            ] + [
                spec_item.get("defaults")
                for spec_item in spec.resource.get("specs") or []
            ]
            resources = {
                resource["path"]: resource["sha256sum"]
                for path in resource_paths
                if path and (resource := gqlapi.get_resource(path))
            }
            spec_state = {
                "spec": asdict(spec),
                "resources": resources,
            }
            spec_id = f"{spec.cluster_name}/{spec.namespace_name}/{spec.provisioner_name}/{spec.provider}/{spec.identifier}"
            state_for_accounts[spec.provisioner_name][spec_id] = spec_state

    return {
        "state": {
            account: {"shard": account, "hash": DeepHash(state).get(state)}
            for account, state in state_for_accounts.items()
        }
    }


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="account_name",
        shard_arg_is_collection=True,
        shard_path_selectors={"state.*.shard"},
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
