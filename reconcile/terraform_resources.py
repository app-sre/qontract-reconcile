import logging
import shutil
import sys
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Collection,
    Optional,
    Sequence,
    cast,
)

from sretoolbox.utils import (
    retry,
    threaded,
)

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.aws_iam_keys import run as disable_keys
from reconcile.change_owners.diff import IDENTIFIER_FIELD_NAME
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
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.external_resources import (
    PROVIDER_AWS,
    get_external_resource_specs,
    managed_external_resources,
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
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "terraform_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 5, 2)
QONTRACT_TF_PREFIX = "qrtf"


def get_tf_namespaces(
    account_names: Optional[Iterable[str]] = None,
) -> list[NamespaceV1]:
    namespaces = get_namespaces()
    return filter_tf_namespaces(namespaces, account_names)


def populate_oc_resources(
    spec: ob.CurrentStateSpec,
    ri: ResourceInventory,
    account_names: Optional[Iterable[str]],
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
    dry_run: bool,
    namespaces: Iterable[NamespaceV1],
    thread_pool_size: int,
    internal: Optional[bool],
    use_jump_host: bool,
    account_names: Optional[Iterable[str]],
) -> tuple[ResourceInventory, Optional[OCMap]]:
    ri = ResourceInventory()
    if dry_run:
        return ri, None
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
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
    settings: Optional[Mapping[str, Any]] = None,
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
    accounts: Iterable[Mapping[str, Any]], filter: Iterable[str]
) -> Collection[Mapping[str, Any]]:
    return [ac for ac in accounts if ac["name"] in filter]


def exclude_accounts_by_name(
    accounts: Iterable[Mapping[str, Any]], filter: Iterable[str]
) -> Collection[Mapping[str, Any]]:
    return [ac for ac in accounts if ac["name"] not in filter]


def validate_account_names(
    accounts: Collection[Mapping[str, Any]], names: Collection[str]
) -> None:
    if len(accounts) != len(names):
        missing_names = set(names) - {a["name"] for a in accounts}
        raise ValueError(
            f"Accounts {missing_names} were provided as arguments, but not found in app-interface. Check your input for typos or for missing AWS account definitions."
        )


def setup(
    dry_run: bool,
    print_to_file: Optional[str],
    thread_pool_size: int,
    internal: Optional[bool],
    use_jump_host: bool,
    include_accounts: Optional[Collection[str]],
    exclude_accounts: Optional[Collection[str]],
) -> tuple[
    ResourceInventory, Optional[OCMap], Terraform, ExternalResourceSpecInventory
]:
    accounts = queries.get_aws_accounts(terraform_state=True)
    if not include_accounts and exclude_accounts:
        excluding = filter_accounts_by_name(accounts, exclude_accounts)
        validate_account_names(excluding, exclude_accounts)
        accounts = exclude_accounts_by_name(accounts, exclude_accounts)
        if len(accounts) == 0:
            raise ValueError("You have excluded all aws accounts, verify your input")
        account_names = tuple(ac["name"] for ac in accounts)
    elif include_accounts:
        accounts = filter_accounts_by_name(accounts, include_accounts)
        validate_account_names(accounts, include_accounts)
    account_names = tuple(a["name"] for a in accounts)
    settings = queries.get_app_interface_settings()

    # build a resource inventory for all the kube secrets managed by the
    # app-interface managed terraform resources
    tf_namespaces = get_tf_namespaces(account_names)
    if not tf_namespaces:
        logging.warning(
            "No terraform namespaces found, consider disabling this integration, account names: "
            f"{', '.join(account_names)}"
        )
    ri, oc_map = fetch_current_state(
        dry_run, tf_namespaces, thread_pool_size, internal, use_jump_host, account_names
    )

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

    return ri, oc_map, tf, ts.resource_spec_inventory


def filter_tf_namespaces(
    namespaces: Iterable[NamespaceV1], account_names: Optional[Iterable[str]]
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


def cleanup_and_exit(
    tf: Optional[Terraform] = None,
    status: bool = False,
    working_dirs: Optional[Mapping[str, str]] = None,
) -> None:
    if working_dirs is None:
        working_dirs = {}
    if tf is None:
        for wd in working_dirs.values():
            shutil.rmtree(wd)
    else:
        tf.cleanup()
    sys.exit(status)


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


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    light: bool = False,
    vault_output_path: str = "",
    account_name: Optional[Sequence[str]] = None,
    exclude_accounts: Optional[Sequence[str]] = None,
    defer: Optional[Callable] = None,
) -> None:
    if exclude_accounts and not dry_run:
        message = "--exclude-accounts is only supported in dry-run mode"
        logging.error(message)
        raise ExcludeAccountsAndDryRunException(message)

    if exclude_accounts and account_name:
        message = "Using --exclude-accounts and --account-name at the same time is not allowed"
        logging.error(message)
        raise ExcludeAccountsAndAccountNameException(message)

    # account_name is a tuple of account names for more detail go to
    # https://click.palletsprojects.com/en/8.1.x/options/#multiple-options
    account_names = account_name

    # acc_name will prevent type error since account_name is not a str
    acc_name: Optional[str] = account_names[0] if account_names else None

    # If we are not running in dry run we don't want to run with more than one account
    if account_names and len(account_names) > 1 and not dry_run:
        message = "Running with multiple accounts is only supported in dry-run mode"
        logging.error(message)
        raise MultipleAccountNamesInDryRunException(message)

    ri, oc_map, tf, resource_specs = setup(
        dry_run,
        print_to_file,
        thread_pool_size,
        internal,
        use_jump_host,
        account_names,
        exclude_accounts,
    )

    if not dry_run and oc_map and defer:
        defer(oc_map.cleanup)

    if print_to_file:
        cleanup_and_exit(tf)
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    if not light:
        disabled_deletions_detected, err = tf.plan(enable_deletion)
        if err:
            cleanup_and_exit(tf, err)
        if disabled_deletions_detected:
            cleanup_and_exit(tf, disabled_deletions_detected)

    if dry_run:
        cleanup_and_exit(tf)

    if not light and tf.should_apply:
        err = tf.apply()
        if err:
            cleanup_and_exit(tf, err)

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
        resource_specs=resource_specs, init_rds_replica_source=True
    )
    # populate the resource inventory with latest output data
    populate_desired_state(ri, resource_specs)

    actions = []
    if oc_map:
        actions = ob.realize_data(
            dry_run, oc_map, ri, thread_pool_size, caller=acc_name
        )

    if actions and vault_output_path:
        write_outputs_to_vault(vault_output_path, resource_specs)

    if ri.has_error_registered():
        err = True
        cleanup_and_exit(tf, err)

    cleanup_and_exit(tf)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    namespaces = get_tf_namespaces()
    resources = []
    for ns_info in namespaces:
        for spec in get_external_resource_specs(
            ns_info.dict(by_alias=True), provision_provider=PROVIDER_AWS
        ):

            def register_resource(
                spec: ExternalResourceSpec, resource: Optional[dict[str, Any]]
            ) -> None:
                if resource:
                    resources.append(
                        {
                            IDENTIFIER_FIELD_NAME: f"{spec.cluster_name}/{spec.namespace_name}/{spec.provisioner_name}/{spec.provider}/{spec.identifier}/{resource.get('path')}",
                            "content_sha": resource.get("sha256sum"),
                            "provisioner": spec.provisioner_name,
                        }
                    )

            defaults = spec.resource.get("defaults")
            if defaults:
                register_resource(spec, gqlapi.get_resource(defaults))
            parameter_group = spec.resource.get("parameter_group")
            if parameter_group:
                register_resource(spec, gqlapi.get_resource(parameter_group))
            for spec_item in spec.resource.get("specs") or []:
                defaults = spec_item.get("defaults")
                if defaults:
                    register_resource(spec, gqlapi.get_resource(defaults))

    return {
        "accounts": queries.get_aws_accounts(terraform_state=True),
        "namespaces": namespaces,
        "resources": resources,
    }


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="account_name",
        shard_arg_is_collection=True,
        shard_path_selectors={
            "accounts[*].name",
            "namespaces[*].externalResources[*].provisioner.name",
            "resources[*].provisioner",
        },
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
