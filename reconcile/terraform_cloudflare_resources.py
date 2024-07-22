import logging
import sys
from collections.abc import Iterable
from typing import (
    Any,
    cast,
)

from sretoolbox.utils import threaded

from reconcile.gql_definitions.terraform_cloudflare_resources import (
    terraform_cloudflare_accounts,
    terraform_cloudflare_resources,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    AWSAccountV1,
    CloudflareAccountV1,
    TerraformCloudflareAccountsQueryData,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceV1,
    TerraformCloudflareResourcesQueryData,
)
from reconcile.openshift_base import (
    CurrentStateSpec,
    init_specs_to_fetch,
    realize_data,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import SecretIncompleteError
from reconcile.utils.external_resource_spec import ExternalResourceSpecInventory
from reconcile.utils.external_resources import (
    PROVIDER_CLOUDFLARE,
    get_external_resource_specs,
    publish_metrics,
)
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.oc_map import (
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    ResourceInventory,
)
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform.config_client import TerraformConfigClientCollection
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    DEFAULT_CLOUDFLARE_ACCOUNT_2FA,
    DEFAULT_CLOUDFLARE_ACCOUNT_TYPE,
    CloudflareAccountConfig,
    TerraformS3BackendConfig,
    TerrascriptCloudflareClient,
    create_cloudflare_terrascript,
)
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "terraform_cloudflare_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcf"


def create_backend_config(
    secret_reader: SecretReaderBase,
    aws_acct: AWSAccountV1,
    cf_acct: CloudflareAccountV1,
) -> TerraformS3BackendConfig:
    aws_acct_creds = secret_reader.read_all_secret(aws_acct.automation_token)

    # default from AWS account file
    tf_state = aws_acct.terraform_state
    if tf_state is None:
        raise ValueError(
            f"AWS account {aws_acct.name} cannot be used for Cloudflare "
            f"account {cf_acct.name} because it does define a terraform state "
        )

    integrations = tf_state.integrations or []
    bucket_key = bucket_name = bucket_region = None
    for i in integrations or []:
        name = i.integration
        if name.replace("-", "_") == QONTRACT_INTEGRATION:
            # we have to ensure the bucket key(file) is unique across
            # Cloudflare accounts to support running per-account
            bucket_key = f"{QONTRACT_INTEGRATION}-{cf_acct.name}.tfstate"
            bucket_name = tf_state.bucket
            bucket_region = tf_state.region
            break

    if bucket_name and bucket_key and bucket_region:
        backend_config = TerraformS3BackendConfig(
            aws_acct_creds["aws_access_key_id"],
            aws_acct_creds["aws_secret_access_key"],
            bucket_name,
            bucket_key,
            bucket_region,
        )
    else:
        raise ValueError(f"No state bucket config found for account {aws_acct.name}")

    return backend_config


def build_clients(
    secret_reader: SecretReaderBase,
    query_accounts: TerraformCloudflareAccountsQueryData,
    selected_account: str | None = None,
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    for cf_acct in query_accounts.accounts or []:
        if selected_account and cf_acct.name != selected_account:
            continue
        cf_acct_creds = secret_reader.read_all_secret(cf_acct.api_credentials)
        if not cf_acct_creds.get("api_token") or not cf_acct_creds.get("account_id"):
            raise SecretIncompleteError(
                f"secret {cf_acct.api_credentials.path} incomplete: api_token and/or account_id missing"
            )
        cf_acct_config = CloudflareAccountConfig(
            cf_acct.name,
            cf_acct_creds["api_token"],
            cf_acct_creds["account_id"],
            cf_acct.enforce_twofactor or DEFAULT_CLOUDFLARE_ACCOUNT_2FA,
            cf_acct.q_type or DEFAULT_CLOUDFLARE_ACCOUNT_TYPE,
        )

        aws_acct = cf_acct.terraform_state_account
        aws_backend_config = create_backend_config(secret_reader, aws_acct, cf_acct)

        ts_config = create_cloudflare_terrascript(
            cf_acct_config,
            aws_backend_config,
            cf_acct.provider_version,
        )

        ts_client = TerrascriptCloudflareClient(ts_config)
        clients.append((cf_acct.name, ts_client))
    return clients


def _build_oc_resources(
    cloudflare_namespaces: Iterable[NamespaceV1],
    secret_reader: SecretReaderBase,
    use_jump_host: bool,
    thread_pool_size: int,
    internal: bool | None = None,
    account_names: Iterable[str] | None = None,
) -> tuple[ResourceInventory, OCMap]:
    ri = ResourceInventory()

    oc_map = init_oc_map_from_namespaces(
        cloudflare_namespaces,
        secret_reader,
        integration=QONTRACT_INTEGRATION,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        internal=internal,
    )

    namespace_mapping = [ns.dict() for ns in cloudflare_namespaces]

    state_specs = init_specs_to_fetch(
        ri, oc_map, namespaces=namespace_mapping, override_managed_types=["Secret"]
    )
    current_state_specs: list[CurrentStateSpec] = [
        s for s in state_specs if isinstance(s, CurrentStateSpec)
    ]
    threaded.run(
        _populate_oc_resources,
        current_state_specs,
        thread_pool_size,
        ri=ri,
        account_names=account_names,
    )

    return ri, oc_map


def _populate_oc_resources(
    spec: CurrentStateSpec,
    ri: ResourceInventory,
    account_names: Iterable[str] | None,
):
    """
    This was taken from terraform_resources and might be a later candidate for DRY.
    """
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
            openshift_resource = OpenshiftResource(
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


def _populate_desired_state(
    ri: ResourceInventory, resource_specs: ExternalResourceSpecInventory
) -> None:
    for spec in resource_specs.values():
        if ri.is_cluster_present(spec.cluster_name):
            oc_resource = spec.build_oc_secret(
                QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
            )

            if not oc_resource.body.get("data"):
                logging.debug(
                    "Skipping oc_resource %s because there is no Secret data (not all resources have outputs)",
                    oc_resource.name,
                )
                continue

            ri.add_desired(
                cluster=spec.cluster_name,
                namespace=spec.namespace_name,
                resource_type=oc_resource.kind,
                name=spec.output_resource_name,
                value=oc_resource,
                privileged=spec.namespace.get("clusterAdmin") or False,
            )


def _write_external_resource_secrets_to_vault(
    vault_path: str,
    resource_specs: ExternalResourceSpecInventory,
    integration_name: str,
) -> None:
    """
    Write the secrets associated with an external resource to Vault. This was taken
    from terraform-resources with minor modifications. We can consider moving this to a
    separate module if we have additional needs for a similar function.
    """
    integration_name = integration_name.replace("_", "-")
    vault_client = cast(_VaultClient, VaultClient())
    for spec in resource_specs.values():
        # A secret can be empty if the terraform-* integrations are not enabled on the cluster
        # the resource is defined on - lets skip vault writes for those right now and
        # give this more thought - e.g. not processing such specs at all when the integration
        # is disabled
        if spec.secret:
            secret_path = f"{vault_path}/{integration_name}/{spec.cluster_name}/{spec.namespace_name}/{spec.output_resource_name}"
            # vault only stores strings as values - by converting to str upfront, we can compare current to desired
            stringified_secret = {k: str(v) for k, v in spec.secret.items()}
            desired_secret = {"path": secret_path, "data": stringified_secret}
            vault_client.write(desired_secret, decode_base64=False)


def _filter_cloudflare_namespaces(
    namespaces: Iterable[NamespaceV1], account_names: set[str]
) -> list[NamespaceV1]:
    """
    Get only the namespaces that have Cloudflare resources and that match account_names.
    """
    cloudflare_namespaces: list[NamespaceV1] = []
    for ns in namespaces:
        if ns.external_resources:
            for resource in ns.external_resources:
                if isinstance(resource, NamespaceTerraformProviderResourceCloudflareV1):
                    if (
                        resource.provider == PROVIDER_CLOUDFLARE
                        and resource.provisioner.name in account_names
                    ):
                        cloudflare_namespaces.append(ns)
    return cloudflare_namespaces


@defer
def run(
    dry_run: bool,
    print_to_file: str | None,
    enable_deletion: bool,
    thread_pool_size: int,
    selected_account: str | None = None,
    vault_output_path: str = "",
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer=None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    query_accounts, query_resources = _get_cloudflare_desired_state()

    if not query_accounts.accounts:
        logging.info("No Cloudflare accounts were detected, nothing to do.")
        sys.exit(ExitCodes.SUCCESS)

    if not query_resources.namespaces:
        logging.info("No namespaces were detected, nothing to do.")
        sys.exit(ExitCodes.SUCCESS)

    if selected_account:
        account_names = [selected_account]
    else:
        account_names = [acct.name for acct in query_accounts.accounts]

    cloudflare_namespaces = _filter_cloudflare_namespaces(
        query_resources.namespaces, set(account_names)
    )

    if not cloudflare_namespaces:
        logging.info("No cloudflare namespaces were detected, nothing to do.")
        sys.exit(ExitCodes.SUCCESS)

    # Build Cloudflare clients
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(secret_reader, query_accounts, selected_account):
        cf_clients.register_client(*client)

    # Register Cloudflare resources
    cf_specs = [
        spec
        for namespace in query_resources.namespaces
        for spec in get_external_resource_specs(
            namespace.dict(by_alias=True), PROVIDER_CLOUDFLARE
        )
        if not selected_account or spec.provisioner_name == selected_account
    ]
    cf_clients.add_specs(cf_specs)

    cf_clients.populate_resources()

    publish_metrics(cf_clients.resource_spec_inventory, QONTRACT_INTEGRATION)

    ri, oc_map = _build_oc_resources(
        cloudflare_namespaces,
        secret_reader,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        internal=internal,
        account_names=account_names,
    )

    if defer:
        defer(oc_map.cleanup)

    working_dirs = cf_clients.dump(print_to_file=print_to_file)

    if print_to_file:
        sys.exit(ExitCodes.SUCCESS)

    tf = TerraformClient(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        [
            acct.dict(by_alias=True)  # convert CloudflareAccountV1 to dict
            for acct in query_accounts.accounts or []
            if acct.name in cf_clients.dump()  # use only if it is a registered client
        ],
        working_dirs,
        thread_pool_size,
    )
    defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        sys.exit(ExitCodes.ERROR)
    if disabled_deletions_detected:
        logging.error("Deletions detected but they are disabled")
        sys.exit(ExitCodes.ERROR)

    if dry_run:
        sys.exit(ExitCodes.SUCCESS)

    err = tf.apply()
    if err:
        sys.exit(ExitCodes.ERROR)

    # refresh output data after terraform apply
    tf.populate_terraform_output_secrets(
        resource_specs=cf_clients.resource_spec_inventory
    )

    # populate the resource inventory with latest output data
    _populate_desired_state(ri, cf_clients.resource_spec_inventory)

    actions = realize_data(
        dry_run, oc_map, ri, thread_pool_size, caller=selected_account
    )

    if actions and vault_output_path:
        _write_external_resource_secrets_to_vault(
            vault_output_path,
            cf_clients.resource_spec_inventory,
            QONTRACT_INTEGRATION.replace("_", "-"),
        )


def _get_cloudflare_desired_state() -> (
    tuple[
        TerraformCloudflareAccountsQueryData,
        TerraformCloudflareResourcesQueryData,
    ]
):
    query_accounts = terraform_cloudflare_accounts.query(query_func=gql.get_api().query)
    query_resources = terraform_cloudflare_resources.query(
        query_func=gql.get_api().query
    )

    return query_accounts, query_resources


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    desired_state = _get_cloudflare_desired_state()

    return {state.__repr_name__(): state.dict() for state in desired_state}
