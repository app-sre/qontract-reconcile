import sys
from typing import Optional, cast

from reconcile import queries
from reconcile.gql_definitions.terraform_cloudflare_resources import (
    terraform_cloudflare_resources,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    AWSAccountV1,
    CloudflareAccountV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    TerraformCloudflareResourcesQueryData,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.github_api import GithubApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform import safe_resource_id
from reconcile.utils.terraform.config_client import TerraformConfigClientCollection
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    CloudflareAccountConfig,
    TerraformS3BackendConfig,
    TerrascriptCloudflareClient,
    create_cloudflare_terrascript,
)
from reconcile.utils.helpers import filter_null

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


def get_resources(
    query_data: TerraformCloudflareResourcesQueryData,
) -> list[NamespaceTerraformProviderResourceCloudflareV1]:
    """Get all Cloudflare V1 resources from the Cloudflare query data"""
    return [
        res
        for namespace in filter_null(query_data.namespaces)
        for res in filter_null(namespace.external_resources)
        if isinstance(res, NamespaceTerraformProviderResourceCloudflareV1)
    ]


def build_clients(
    secret_reader: SecretReader,
    query_data: TerraformCloudflareResourcesQueryData,
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    for extres in get_resources(query_data):
        cf_acct = extres.provisioner

        cf_acct_creds = secret_reader.read_all({"path": cf_acct.api_credentials.path})
        cf_acct_config = CloudflareAccountConfig(
            cf_acct.name,
            cf_acct_creds.get("api_token"),
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


def get_github_file(repo: str, path: str, ref: str) -> str:
    settings = queries.get_app_interface_settings()
    gh_instance = queries.get_github_instance()
    gh = GithubApi(gh_instance, repo, settings)
    content = gh.get_file(path, ref)
    if content is None:
        raise ValueError(
            f"Could not retrieve Github file content at {repo} "
            f"for file path {path} at ref {ref}"
        )
    return content.decode("utf-8")


def build_specs(
    query_data: TerraformCloudflareResourcesQueryData,
) -> list[ExternalResourceSpec]:

    specs = []
    for extres in get_resources(query_data):
        provisioner_name = extres.provisioner.name
        for res in extres.resources or []:
            res = cast(NamespaceTerraformResourceCloudflareZoneV1, res)
            zone_identifier = safe_resource_id(res.zone)
            specs.append(
                ExternalResourceSpec(
                    "cloudflare_zone",
                    {"name": provisioner_name, "automationToken": {}},
                    {
                        "provider": "cloudflare_zone",
                        "identifier": zone_identifier,
                        "zone": res.zone,
                        "plan": res.plan if res.plan else "free",
                        "type": res.q_type if res.q_type else "full",
                        "settings": res.settings,
                    },
                    {},
                )
            )

            # If argo is defined on the zone, add an argo resource spec
            if res.argo:
                specs.append(
                    ExternalResourceSpec(
                        "cloudflare_argo",
                        {"name": provisioner_name, "automationToken": {}},
                        {
                            "provider": "cloudflare_argo",
                            "identifier": zone_identifier,
                            "depends_on": [f"cloudflare_zone.{zone_identifier}"],
                            "zone_id": f"${{cloudflare_zone.{zone_identifier}.id}}",
                            "smart_routing": "on" if res.argo.smart_routing else "off",
                            "tiered_caching": "on" if res.argo.smart_routing else "off",
                        },
                        {},
                    )
                )

            # Add zone records
            for record in filter_null(res.records):
                specs.append(
                    ExternalResourceSpec(
                        "cloudflare_record",
                        {"name": provisioner_name, "automationToken": {}},
                        {
                            "provider": "cloudflare_record",
                            "identifier": safe_resource_id(record.name),
                            "depends_on": [f"cloudflare_zone.{zone_identifier}"],
                            "zone_id": f"${{cloudflare_zone.{zone_identifier}.id}}",
                            "name": record.name,
                            "type": record.q_type,
                            "ttl": record.ttl,
                            "value": record.value,
                            "proxied": record.proxied,
                        },
                        {},
                    )
                )

            # Add zone workers
            for worker in filter_null(res.workers):
                if worker.script.content_from_github:
                    gh_repo = worker.script.content_from_github.repo
                    gh_path = worker.script.content_from_github.path
                    gh_ref = worker.script.content_from_github.ref
                    wrk_script_content = get_github_file(gh_repo, gh_path, gh_ref)

                worker_script_vars = [
                    {"name": var.name, "text": var.text}
                    for var in worker.script.vars or []
                ]
                specs.append(
                    ExternalResourceSpec(
                        "cloudflare_worker",
                        {"name": provisioner_name, "automationToken": {}},
                        {
                            "provider": "cloudflare_worker",
                            "identifier": safe_resource_id(worker.identifier),
                            "depends_on": [f"cloudflare_zone.{zone_identifier}"],
                            "zone_id": f"${{cloudflare_zone.{zone_identifier}.id}}",
                            "pattern": worker.pattern,
                            "script_name": worker.script.name,
                            "script_content": wrk_script_content,
                            "script_vars": worker_script_vars,
                        },
                        {},
                    )
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

    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)

    query_data = terraform_cloudflare_resources.query(query_func=gql.get_api().query)

    # Build Cloudflare clients
    cf_clients = TerraformConfigClientCollection()
    for client in build_clients(secret_reader, query_data):
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
