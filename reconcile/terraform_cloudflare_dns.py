import logging
import sys
from collections.abc import (
    Callable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

from reconcile.gql_definitions.terraform_cloudflare_dns import (
    terraform_cloudflare_zones,
)
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    AWSAccountV1,
    CloudflareAccountV1,
    CloudflareDnsZoneQueryData,
    CloudflareDnsZoneV1,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import SecretIncompleteError
from reconcile.utils.external_resources import ExternalResourceSpec
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
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

DEFAULT_NAMESPACE: Mapping[str, Any] = {
    "name": None,
    "cluster": {"name": None},
    "environment": {"name": None},
    "app": {"name": None},
}
DEFAULT_PROVISIONER_PROVIDER = "cloudflare"
DEFAULT_PROVIDER = "zone"
DEFAULT_EXCLUDE_KEY = "account"


class TerraformCloudflareDNSIntegrationParams(PydanticRunParams):
    enable_deletion: bool
    thread_pool_size: int
    selected_account: Optional[str] = None
    selected_zone: Optional[str] = None
    print_to_file: Optional[str]


class TerraformCloudflareDNSIntegration(
    QontractReconcileIntegration[TerraformCloudflareDNSIntegrationParams]
):
    def __init__(self, params: TerraformCloudflareDNSIntegrationParams) -> None:
        super().__init__(params)
        self.qontract_integration = "terraform_cloudflare_dns"
        self.qontract_integration_version = make_semver(0, 1, 0)
        self.qontract_tf_prefix = "qrtfcfdns"

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    def run(self, dry_run: bool) -> None:
        self.run_with_defer(dry_run)  # pylint: disable=no-value-for-parameter

    @defer
    def run_with_defer(self, dry_run: bool, defer: Callable) -> None:
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        query_zones = self._get_cloudflare_desired_state()

        # Build Cloudflare clients
        cf_clients = TerraformConfigClientCollection()
        zone_clients = build_clients(
            secret_reader,
            query_zones,
            self.qontract_integration,
            self.params.selected_account,
            self.params.selected_zone,
        )

        for client in zone_clients:
            cf_clients.register_client(*client)

        zone_external_resource_specs = cloudflare_dns_zone_to_external_resource(
            query_zones.zones
        )
        cf_specs = [
            spec
            for spec in zone_external_resource_specs
            if not self.params.selected_account
            or spec.provisioner_name == self.params.selected_account
            if not self.params.selected_zone
            or spec.identifier == self.params.selected_zone
        ]

        cf_clients.add_specs(cf_specs)

        cf_clients.populate_resources()

        working_dirs = cf_clients.dump(print_to_file=self.params.print_to_file)

        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)

        accts_per_zone = []
        for zone in query_zones.zones or []:
            acct = zone.account.dict(by_alias=True)
            acct["name"] = f"{zone.account.name}-{zone.identifier}"
            accts_per_zone.append(acct)

        tf = TerraformClient(
            self.qontract_integration,
            self.qontract_integration_version,
            self.qontract_tf_prefix,
            accts_per_zone,
            working_dirs,
            self.params.thread_pool_size,
        )

        defer(tf.cleanup)

        disabled_deletions_detected, err = tf.plan(self.params.enable_deletion)
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

    def _get_cloudflare_desired_state(self) -> CloudflareDnsZoneQueryData:
        query_zones = terraform_cloudflare_zones.query(query_func=gql.get_api().query)
        logging.debug(query_zones)

        return query_zones

    def get_early_exit_desired_state(
        self, *args: tuple, **kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        desired_state = self._get_cloudflare_desired_state()

        # return {"zones":desired_state.zones}
        return desired_state.dict()

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="selected_zone",
            shard_path_selectors={"zones[*].identifier"},
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )


def create_backend_config(
    secret_reader: SecretReaderBase,
    aws_acct: AWSAccountV1,
    cf_acct: CloudflareAccountV1,
    zone: str,
    integration_name: str,
) -> TerraformS3BackendConfig:
    aws_acct_creds = secret_reader.read_all_secret(aws_acct.automation_token)

    # default from AWS account file
    tf_state = aws_acct.terraform_state
    if tf_state is None:
        raise ValueError(
            f"AWS account {aws_acct.name} cannot be used for Cloudflare "
            f"account {cf_acct.name} because it doesn't define a terraform state "
        )

    integrations = tf_state.integrations or []
    for i in integrations or []:
        name = i.integration
        if name.replace("-", "_") == integration_name:
            # Currently terraform-state-1.yml can only have one bucket
            # but multiple integrations, which means without schema changes
            # we have to ensure the bucket key(file) is unique across
            # all Cloudflare zones to support sharding per zone.

            bucket_key = f"{integration_name}-{cf_acct.name}-{zone}.tfstate"
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


def get_cf_acct_config(
    cf_acct: CloudflareAccountV1,
    secret_reader: SecretReaderBase,
) -> CloudflareAccountConfig:
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
    return cf_acct_config


def build_clients(
    secret_reader: SecretReaderBase,
    query_zones: CloudflareDnsZoneQueryData,
    integration_name: str,
    selected_account: Optional[str] = None,
    selected_zone: Optional[str] = None,
) -> list[tuple[str, TerrascriptCloudflareClient]]:
    clients = []
    cf_acct_configs: dict[str, CloudflareAccountConfig] = {}
    for zone in query_zones.zones or []:
        cf_acct = zone.account
        cf_acct_name = cf_acct.name

        if selected_account and cf_acct_name != selected_account:
            continue
        if selected_zone and zone.identifier != selected_zone:
            continue
        if cf_acct_name in cf_acct_configs:
            cf_acct_config = cf_acct_configs[cf_acct_name]
        else:
            cf_acct_config = get_cf_acct_config(cf_acct, secret_reader)
            cf_acct_configs[cf_acct_name] = cf_acct_config
        aws_acct = cf_acct.terraform_state_account
        aws_backend_config = create_backend_config(
            secret_reader,
            aws_acct,
            cf_acct,
            zone.identifier,
            integration_name=integration_name,
        )

        ts_config = create_cloudflare_terrascript(
            cf_acct_config,
            aws_backend_config,
            cf_acct.provider_version,
            is_managed_account=False,
        )

        ts_client = TerrascriptCloudflareClient(ts_config)
        clients.append((f"{cf_acct.name}-{zone.identifier}", ts_client))

    return clients


def cloudflare_dns_zone_to_external_resource(
    zones: Optional[list[CloudflareDnsZoneV1]],
) -> list[ExternalResourceSpec]:
    """
    This is a method that massage a list of CloudflareDnsZoneV1 into ExternalResourceSpec
    by filling in some fake namespace data. It is needed because cloudflare_client's add_spec
    method only takes ExternalResourceSpec, which was designed that way since most of our
    cloud resource is tied to a namespace. If more use cases like this come up,
    we can add new classes for this purpose using Adapter pattern
    """
    external_resource_specs: list[ExternalResourceSpec] = []
    for zone in zones or []:
        if zone.delete:
            continue
        external_resource_spec = ExternalResourceSpec(
            provision_provider=DEFAULT_PROVISIONER_PROVIDER,
            provisioner={"name": f"{zone.account.name}-{zone.identifier}"},
            namespace=DEFAULT_NAMESPACE,
            resource=zone.dict(by_alias=True, exclude={DEFAULT_EXCLUDE_KEY}),
        )
        external_resource_spec.resource["provider"] = DEFAULT_PROVIDER
        external_resource_spec.resource["records"] = [
            record.dict(by_alias=True) for record in zone.records or []
        ]
        external_resource_specs.append(external_resource_spec)
    return external_resource_specs
