import logging
import sys
from typing import (
    Any,
    Optional,
    Tuple,
)

from reconcile import queries
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
    TerraformCloudflareResourcesQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import SecretIncompleteError
from reconcile.utils.external_resources import (
    PROVIDER_CLOUDFLARE,
    get_external_resource_specs,
)
from reconcile.utils.secret_reader import SecretReader
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

QONTRACT_INTEGRATION = "terraform_cloudflare_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcf"


def create_backend_config(
    secret_reader: SecretReader,
    aws_acct: AWSAccountV1,
    cf_acct: CloudflareAccountV1,
) -> TerraformS3BackendConfig:
    aws_acct_creds = secret_reader.read_all({"path": aws_acct.automation_token.path})

    # default from AWS account file
    tf_state = aws_acct.terraform_state
    if tf_state is None:
        raise ValueError(
            f"AWS account {aws_acct.name} cannot be used for Cloudflare "
            f"account {cf_acct.name} because it does define a terraform state "
        )

    integrations = tf_state.integrations or []
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
    secret_reader: SecretReader,
    query_accounts: TerraformCloudflareAccountsQueryData,
    selected_account: Optional[str] = None,
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    for cf_acct in query_accounts.accounts or []:
        if selected_account and cf_acct.name != selected_account:
            continue
        cf_acct_creds = secret_reader.read_all({"path": cf_acct.api_credentials.path})
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


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str],
    enable_deletion: bool,
    thread_pool_size: int,
    selected_account=None,
    defer=None,
) -> None:
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    query_accounts, query_resources = _get_cloudflare_desired_state()

    # Build Cloudflare clients
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(secret_reader, query_accounts, selected_account):
        cf_clients.register_client(*client)

    # Register Cloudflare resources
    cf_specs = [
        spec
        for namespace in query_resources.namespaces or []
        for spec in get_external_resource_specs(
            namespace.dict(by_alias=True), PROVIDER_CLOUDFLARE
        )
        if not selected_account or spec.provisioner_name == selected_account
    ]
    cf_clients.add_specs(cf_specs)

    cf_clients.populate_resources()

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


def _get_cloudflare_desired_state() -> Tuple[
    TerraformCloudflareAccountsQueryData, TerraformCloudflareResourcesQueryData
]:
    query_accounts = terraform_cloudflare_accounts.query(query_func=gql.get_api().query)
    query_resources = terraform_cloudflare_resources.query(
        query_func=gql.get_api().query
    )

    return query_accounts, query_resources


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    desired_state = _get_cloudflare_desired_state()

    return {state.__repr_name__(): state.dict() for state in desired_state}
