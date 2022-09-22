import logging
import sys
from typing import Optional

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
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.external_resources import (
    PROVIDER_CLOUDFLARE,
    get_external_resource_specs,
)
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform.config_client import TerraformConfigClientCollection
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    CloudflareAccountConfig,
    TerraformS3BackendConfig,
    TerrascriptCloudflareClient,
    create_cloudflare_terrascript,
)
from reconcile.status import ExitCodes

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
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    for cf_acct in query_accounts.accounts or []:
        cf_acct_creds = secret_reader.read_all({"path": cf_acct.api_credentials.path})
        cf_acct_config = CloudflareAccountConfig(
            cf_acct.name,
            cf_acct_creds.get("api_token"),
            cf_acct_creds.get("account_id"),
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
    defer=None,
) -> None:

    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    # Build Cloudflare clients
    query_accounts = terraform_cloudflare_accounts.query(query_func=gql.get_api().query)
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(secret_reader, query_accounts):
        cf_clients.register_client(*client)

    # Register Cloudflare resources
    query_resources = terraform_cloudflare_resources.query(
        query_func=gql.get_api().query
    )
    cf_specs = [
        spec
        for namespace in query_resources.namespaces or []
        for spec in get_external_resource_specs(
            namespace.dict(by_alias=True), PROVIDER_CLOUDFLARE
        )
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
        [{"name": name} for name in cf_clients.dump()],
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
