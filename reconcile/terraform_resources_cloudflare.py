import logging
import sys
from typing import Any, Optional
from reconcile import queries
from reconcile.gql_queries.terraform_resources_cloudflare import (
    terraform_resources_cloudflare,
)
from reconcile.gql_queries.terraform_resources_cloudflare.terraform_resources_cloudflare import (
    AWSAccountV1,
    CloudflareAccountV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    TerraformResourcesCloudflareQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform.config_client import TerraformConfigClientCollection
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    create_cloudflare_terrascript,
    CloudflareAccountConfig,
    TerraformS3BackendConfig,
    TerrascriptCloudflareClient,
)
from reconcile.utils.terrascript_aws_client import safe_resource_id


QONTRACT_INTEGRATION = "terraform_resources_cloudflare"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtfcf"


def create_cloudflare_account_config(
    settings: dict[str, Any], cf_acct: CloudflareAccountV1
) -> CloudflareAccountConfig:
    secret_reader = SecretReader(settings=settings)
    cf_acct_creds = secret_reader.read_all({"path": cf_acct.api_credentials.path})
    return CloudflareAccountConfig(
        cf_acct.name,
        cf_acct_creds.get("email"),
        cf_acct_creds.get("api_token"),
        cf_acct_creds.get("account_id"),
    )


def create_backend_config(
    settings: dict[str, Any],
    aws_acct: AWSAccountV1,
    cf_acct: CloudflareAccountV1,
) -> TerraformS3BackendConfig:
    secret_reader = SecretReader(settings=settings)
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


def get_resources(
    query_data: TerraformResourcesCloudflareQueryData,
) -> list[NamespaceTerraformProviderResourceCloudflareV1]:
    """Get all Cloudflare V1 resources from the Cloudflare query data"""
    return [
        res
        for namespace in query_data.namespaces or []
        for res in namespace.external_resources or []
        if isinstance(res, NamespaceTerraformProviderResourceCloudflareV1)
    ]


def build_clients(
    settings: dict[str, Any],
    query_data: TerraformResourcesCloudflareQueryData,
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    for extres in get_resources(query_data):
        cf_acct = extres.provisioner
        cf_acct_config = create_cloudflare_account_config(settings, cf_acct)

        aws_acct = cf_acct.terraform_state_account
        aws_backend_config = create_backend_config(settings, aws_acct, cf_acct)

        ts_config = create_cloudflare_terrascript(
            cf_acct_config,
            aws_backend_config,
            cf_acct.provider_version,
        )

        ts_client = TerrascriptCloudflareClient(ts_config)
        clients.append((cf_acct.name, ts_client))
    return clients


def build_specs(
    query_data: TerraformResourcesCloudflareQueryData,
) -> list[ExternalResourceSpec]:

    specs = []
    for extres in get_resources(query_data):
        provisioner_name = extres.provisioner.name
        for res in extres.resources or []:
            if isinstance(res, NamespaceTerraformResourceCloudflareZoneV1):
                specs.append(
                    ExternalResourceSpec(
                        "cloudflare_zone",
                        {"name": provisioner_name, "automationToken": {}},
                        {
                            "provider": "cloudflare_zone",
                            "identifier": safe_resource_id(res.zone),
                            "zone": res.zone,
                            "plan": res.plan if res.plan else "free",
                            "type": res.q_type if res.q_type else "full",
                            "settings": res.settings,
                            "argo": res.argo.dict() if res.argo else None,
                            "records": [r.dict() for r in res.records or []],
                            "workers": [r.dict() for r in res.workers or []],
                        },
                        {},
                    )
                )
            else:
                logging.warning(
                    f"Unhandled resource type received: {type(res).__name__}"
                )
    return specs


@defer
def run(
    dry_run: bool,
    print_to_file: Optional[str],
    enable_deletion: bool,
    thread_pool_size: int,
    defer=None,
) -> None:

    gqlapi = gql.get_api()
    settings = queries.get_app_interface_settings()
    res = gqlapi.query(terraform_resources_cloudflare.query_string())
    if res is None:
        logging.error("Aborting due to an error running the GraphQL query")
        sys.exit(ExitCodes.ERROR)

    query_data: TerraformResourcesCloudflareQueryData = (
        TerraformResourcesCloudflareQueryData(**res)
    )

    # Build Cloudflare clients
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(settings, query_data):
        cf_clients.register_client(*client)

    # Register Cloudflare resources
    cf_specs = build_specs(query_data)
    cf_clients.add_specs(cf_specs)

    cf_clients.populate_resources()

    working_dirs = cf_clients.dump(print_to_file=print_to_file)

    if print_to_file:
        sys.exit()

    tf = TerraformClient(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        [{"name": name for name in cf_clients.dump()}],
        working_dirs,
        thread_pool_size,
    )
    defer(tf.cleanup)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        sys.exit(1)
    if disabled_deletions_detected:
        sys.exit(1)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(1)
