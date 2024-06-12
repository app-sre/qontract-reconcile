import logging
import sys
from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from typing import Any

from deepdiff import DeepHash

from reconcile.gql_definitions.terraform_cloudflare_dns import (
    app_interface_cloudflare_dns_settings,
    terraform_cloudflare_zones,
)
from reconcile.gql_definitions.terraform_cloudflare_dns.app_interface_cloudflare_dns_settings import (
    AppInterfaceSettingCloudflareDNSQueryData,
)
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    CloudflareDnsRecordV1,
    CloudflareDnsZoneQueryData,
    CloudflareDnsZoneV1,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.defer import defer
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
from reconcile.utils.terraform.config_client import (
    ClientAlreadyRegisteredError,
    TerraformConfigClientCollection,
)
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_client import (
    DEFAULT_PROVIDER_RPS,
    DNSZoneShardingStrategy,
    IntegrationUndefined,
    InvalidTerraformState,
    TerrascriptCloudflareClientFactory,
)
from reconcile.utils.terrascript.models import (
    CloudflareAccount,
    Integration,
    TerraformStateS3,
)

DEFAULT_NAMESPACE: Mapping[str, Any] = {
    "name": None,
    "cluster": {"name": None},
    "environment": {"name": None},
    "app": {"name": None},
}
DEFAULT_PROVISIONER_PROVIDER = "cloudflare"
DEFAULT_PROVIDER = "zone"
DEFAULT_EXCLUDE_KEY = {
    "account",
    "max_records",
}  # These two keys are added for App Interface, not part of Terraform resource specs.
DEFAULT_CLOUDFLARE_ZONE_RECORDS_MAX = 500


class TerraformCloudflareDNSIntegrationParams(PydanticRunParams):
    enable_deletion: bool
    thread_pool_size: int
    selected_account: str | None = None
    selected_zone: str | None = None
    print_to_file: str | None


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

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        settings = self._get_app_interface_settings()

        if not settings.settings:
            raise RuntimeError("App interface setting undefined.")

        if settings.settings[0].vault is None:
            raise RuntimeError("App interface vault setting undefined.")

        default_max_records = (
            settings.settings[0].cloudflare_dns_zone_max_records
            or DEFAULT_CLOUDFLARE_ZONE_RECORDS_MAX
        )

        if not settings.settings[0].cloudflare_dns_zone_max_records:
            logging.debug(
                f"Setting the App Interface default Cloudflare DNS zone to the default {DEFAULT_CLOUDFLARE_ZONE_RECORDS_MAX}"
            )

        secret_reader = create_secret_reader(use_vault=settings.settings[0].vault)

        query_zones = self._get_cloudflare_desired_state()

        if not query_zones.zones:
            sys.exit(ExitCodes.SUCCESS)

        ensure_record_number_not_exceed_max(query_zones.zones, default_max_records)

        if are_record_identifiers_duplicated_within_zone(query_zones):
            logging.error("Duplicate DNS record identifier(s) detected.")
            sys.exit(ExitCodes.ERROR)

        # Build Cloudflare clients
        cf_clients = build_cloudflare_terraform_config_collection(
            secret_reader,
            query_zones,
            self.qontract_integration,
            self.params.selected_account,
            self.params.selected_zone,
        )

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

        if defer:
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

    def _get_app_interface_settings(self) -> AppInterfaceSettingCloudflareDNSQueryData:
        query_app_interface_settings = app_interface_cloudflare_dns_settings.query(
            query_func=gql.get_api().query
        )
        logging.debug(query_app_interface_settings)

        return query_app_interface_settings

    def get_early_exit_desired_state(
        self, *args: tuple, **kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        desired_state = self._get_cloudflare_desired_state()

        return {
            "state": {
                z.identifier: {"shard": z.identifier, "hash": DeepHash(z).get(z)}
                for z in desired_state.zones or []
            }
        }

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="selected_zone",
            shard_path_selectors={"state.*.shard"},
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )


def are_record_identifiers_duplicated_within_zone(
    zone_query_data: CloudflareDnsZoneQueryData,
) -> bool:
    duplicate_exist = False
    for zone in zone_query_data.zones or []:
        existing_records = set()
        for record in zone.records or []:
            record_id = record.identifier
            if record_id not in existing_records:
                existing_records.add(record_id)
            else:
                logging.warning(f"{record_id} already exists in zone {zone.identifier}")
                duplicate_exist = True
    return duplicate_exist


def ensure_record_number_not_exceed_max(
    zones: list[CloudflareDnsZoneV1], default_max_records: int
) -> None:
    for zone in zones:
        if not zone.records:
            continue
        num_records = len(zone.records)
        if not zone.max_records:
            max_records = default_max_records
            logging.debug(
                f"Setting max_records for zone {zone.identifier} to the default max records {default_max_records}"
            )
        else:
            max_records = zone.max_records
        if max_records < num_records:
            raise RuntimeError(
                f"The number of records ({num_records}) in zone {zone.identifier} exceeds the configured max_items: {max_records}"
            )


def get_cloudflare_provider_rps(
    records: Sequence[CloudflareDnsRecordV1] | None,
) -> int:
    """
    Setting Cloudlare Terraform provider's RPS based on the size of the zone to improve performance of MR checks.
    Specifically it was observed that 1000 records zone will result in around 250 seconds build time, and it become
    problematic for MR merge throughput when exceeding 5 minutes. Therefore setting rps lower for smaller zone to
    save throttle quota, and higher for the large zones so MR checks won't take more than 250 seconds.
    """

    if not records:
        return DEFAULT_PROVIDER_RPS
    size = len(records)
    return min(-(-size // 50), DEFAULT_PROVIDER_RPS)


def build_cloudflare_terraform_config_collection(
    secret_reader: SecretReaderBase,
    query_zones: CloudflareDnsZoneQueryData,
    qontract_integration: str,
    selected_account: str | None,
    selected_zone: str | None,
) -> TerraformConfigClientCollection:
    cf_clients = TerraformConfigClientCollection()
    cf_accounts: dict[str, CloudflareAccount] = {}
    for zone in query_zones.zones or []:
        cf_acct = zone.account
        cf_acct_name = cf_acct.name

        if selected_account and cf_acct_name != selected_account:
            continue
        if selected_zone and zone.identifier != selected_zone:
            continue

        if cf_acct_name in cf_accounts:
            cf_account = cf_accounts[cf_acct_name]
        else:
            cf_account = CloudflareAccount(
                cf_acct_name,
                zone.account.api_credentials,
                zone.account.enforce_twofactor,
                zone.account.q_type,
                zone.account.provider_version,
            )
            cf_accounts[cf_acct_name] = cf_account

        tf_state = zone.account.terraform_state_account.terraform_state
        if not tf_state:
            raise ValueError(
                f"AWS account {zone.account.terraform_state_account.name} cannot be used for Cloudflare "
                f"account {cf_account.name} because it does not define a Terraform state "
            )
        bucket = tf_state.bucket
        region = tf_state.region
        integrations = tf_state.integrations

        if not bucket:
            raise InvalidTerraformState("Terraform state must have bucket defined")
        if not region:
            raise InvalidTerraformState("Terraform state must have region defined")

        integration = None
        for i in integrations:
            if i.integration.replace("-", "_") == qontract_integration:
                integration = i
                break

        if not integration:
            raise IntegrationUndefined(
                f"Must declare integration name under Terraform state in {zone.account.terraform_state_account.name} AWS account for {cf_account.name} Cloudflare account in app-interface"
            )

        tf_state_s3 = TerraformStateS3(
            zone.account.terraform_state_account.automation_token,
            bucket,
            region,
            Integration(integration.integration.replace("-", "_"), integration.key),
        )

        rps = get_cloudflare_provider_rps(zone.records)

        client = TerrascriptCloudflareClientFactory.get_client(
            tf_state_s3,
            cf_account,
            DNSZoneShardingStrategy(cf_account, zone.identifier),
            secret_reader,
            False,
            rps,
        )

        try:
            cf_clients.register_client(f"{cf_account.name}-{zone.identifier}", client)
        except ClientAlreadyRegisteredError:
            pass

    return cf_clients


def cloudflare_dns_zone_to_external_resource(
    zones: list[CloudflareDnsZoneV1] | None,
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
            resource=zone.dict(by_alias=True, exclude=DEFAULT_EXCLUDE_KEY),
        )
        external_resource_spec.resource["provider"] = DEFAULT_PROVIDER
        external_resource_spec.resource["records"] = [
            record.dict(by_alias=True) for record in zone.records or []
        ]
        external_resource_specs.append(external_resource_spec)
    return external_resource_specs
