import tempfile
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable
from dataclasses import dataclass

from terrascript import (
    Backend,
    Data,
    Output,
    Resource,
    Terraform,
    Terrascript,
    Variable,
    provider,
)

from reconcile.cli import TERRAFORM_VERSION
from reconcile.utils.exceptions import SecretIncompleteError
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.terraform.config import TerraformS3BackendConfig
from reconcile.utils.terraform.config_client import TerraformConfigClient
from reconcile.utils.terrascript.cloudflare_resources import (
    cloudflare_account,
    create_cloudflare_terrascript_resource,
)
from reconcile.utils.terrascript.models import (
    CloudflareAccount,
    Integration,
    TerraformStateS3,
)

TMP_DIR_PREFIX = "terrascript-cloudflare-"

DEFAULT_CLOUDFLARE_ACCOUNT_TYPE = "standard"
DEFAULT_CLOUDFLARE_ACCOUNT_2FA = False
DEFAULT_IS_MANAGED_CLOUDFLARE_ACCOUNT = True
DEFAULT_PROVIDER_RPS = 4


@dataclass
class CloudflareAccountConfig:
    """Configuration related to authenticating API calls to Cloudflare."""

    name: str
    api_token: str
    account_id: str
    enforce_twofactor: bool = DEFAULT_CLOUDFLARE_ACCOUNT_2FA
    type: str = DEFAULT_CLOUDFLARE_ACCOUNT_TYPE
    is_managed_account: bool = DEFAULT_IS_MANAGED_CLOUDFLARE_ACCOUNT


def create_cloudflare_terrascript(
    account_config: CloudflareAccountConfig,
    backend_config: TerraformS3BackendConfig,
    provider_version: str,
    provider_rps: int = DEFAULT_PROVIDER_RPS,
    is_managed_account: bool = True,
) -> Terrascript:
    """
    Configures a Terrascript class with the required provider(s) and backend
    configuration.

    This is offloaded to a separate function to avoid mixing additional
    logic into TerrascriptCloudflareClient.

    :param account_config: CloudflareAccount configuration.
    :param backend_config: S3 as backend to store Terraform state.
    :param provider_version: Terraform Cloudflare provider version.
    :is_managed_account:
            If the target cloudflare account is being managed by the caller or not.
            Currently this is deferred to terraform-cloudflare-resources.
            Until further improvement(Tracked by APPSRE-7035),
            this argument can be set to False in other integrations.
            Defaults to True.

    :return: a Terrascript object that contains corresponding resources
    """
    terrascript = Terrascript()

    backend = Backend(
        "s3",
        access_key=backend_config.access_key,
        secret_key=backend_config.secret_key,
        bucket=backend_config.bucket,
        key=backend_config.key,
        region=backend_config.region,
    )

    required_providers = {
        "cloudflare": {
            "source": "cloudflare/cloudflare",
            "version": provider_version,
        }
    }

    terrascript += Terraform(
        backend=backend,
        required_providers=required_providers,
        required_version=TERRAFORM_VERSION[0],
    )

    cloudflare_provider_values = {
        "api_token": account_config.api_token,
        "rps": provider_rps,
    }
    if provider_version.startswith("3"):
        cloudflare_provider_values["account_id"] = (
            account_config.account_id
        )  # needed for some resources, see note below

    terrascript += provider.cloudflare(**cloudflare_provider_values)

    cloudflare_account_values = {
        "name": account_config.name,
        "enforce_twofactor": account_config.enforce_twofactor,
        "type": account_config.type,
    }

    if is_managed_account:
        terrascript += cloudflare_account(
            account_config.name,
            **cloudflare_account_values,
        )

    # Some resources need "account_id" to be set at the resource level
    # The cloudflare provider is being migrated from settings account_id at the provider
    # level to requiring it at the resource level, for resources that needs it.
    # This is also listed in version 4.x breaking changes:
    #   https://github.com/cloudflare/terraform-provider-cloudflare/issues/1646
    terrascript += Variable(
        "account_id", type="string", default=account_config.account_id
    )

    return terrascript


class TerrascriptCloudflareClient(TerraformConfigClient):
    """
    Build the Terrascript configuration, collect resources, and return Terraform JSON
    configuration.

    There's actually very little that's specific to Cloudflare in this class. This could
    become a more general TerrascriptClient that could in theory support any resource
    types with some minor modifications to how resource classes (self._resource_classes)
    are tracked.
    """

    def __init__(
        self,
        ts_client: Terrascript,
    ) -> None:
        self._terrascript = ts_client
        self._resource_specs: ExternalResourceSpecInventory = {}

    def add_spec(self, spec: ExternalResourceSpec) -> None:
        self._resource_specs[spec.id_object()] = spec

    def populate_resources(self) -> None:
        """
        Add the resource spec to Terrascript using the resource-specific classes
        to determine which resources to create.
        """
        for spec in self._resource_specs.values():
            resources_to_add = create_cloudflare_terrascript_resource(spec)
            self._add_resources(resources_to_add)

    def dump(self, existing_dir: str | None = None) -> str:
        """Write the Terraform JSON representation of the resources to disk"""
        if existing_dir is None:
            working_dir = tempfile.mkdtemp(prefix=TMP_DIR_PREFIX)
        else:
            working_dir = existing_dir
        with open(
            working_dir + "/config.tf.json", "w", encoding="locale"
        ) as terraform_config_file:
            terraform_config_file.write(self.dumps())

        return working_dir

    def dumps(self) -> str:
        """Return the Terraform JSON representation of the resources"""
        return str(self._terrascript)

    def _add_resources(self, tf_resources: Iterable[Resource | Output | Data]) -> None:
        for resource in tf_resources:
            self._terrascript.add(resource)


class TerraformS3StateNamingStrategy(ABC):
    @abstractmethod
    def get_object_key(self, qr_integration: Integration) -> str:
        pass


class Default(TerraformS3StateNamingStrategy):
    def get_object_key(self, qr_integration: Integration) -> str:
        return qr_integration.key


class AccountShardingStrategy(TerraformS3StateNamingStrategy):
    """
    This strategy is in place until we solve for keyStrategy as specified in
    https://issues.redhat.com/browse/APPSRE-6933
    """

    def __init__(self, account: CloudflareAccount):
        super().__init__()
        self.account: CloudflareAccount = account

    def get_object_key(self, qr_integration: Integration) -> str:
        return f"{qr_integration.name}-{self.account.name}.tfstate"


class DNSZoneShardingStrategy(TerraformS3StateNamingStrategy):
    def __init__(self, account: CloudflareAccount, zone_identifier: str):
        super().__init__()
        self.account: CloudflareAccount = account
        self.zone: str = zone_identifier

    def get_object_key(self, qr_integration: Integration) -> str:
        old_integration_key = qr_integration.name.replace(
            "-", "_"
        )  # This is because the state file was already created using this name before the refactoring
        return f"{old_integration_key}-{self.account.name}-{self.zone}.tfstate"


class TerrascriptCloudflareClientFactory:
    @staticmethod
    def _create_backend_config(
        tf_state_s3: TerraformStateS3, key: str, secret_reader: SecretReaderBase
    ) -> TerraformS3BackendConfig:
        aws_acct_creds = secret_reader.read_all_secret(tf_state_s3.automation_token)
        aws_access_key_id = aws_acct_creds.get("aws_access_key_id")
        aws_secret_access_key = aws_acct_creds.get("aws_secret_access_key")
        if not aws_access_key_id or not aws_secret_access_key:
            raise SecretIncompleteError(
                f"secret {tf_state_s3.automation_token} incomplete: aws_access_key_id and/or aws_secret_access_key missing"
            )

        return TerraformS3BackendConfig(
            aws_access_key_id,
            aws_secret_access_key,
            tf_state_s3.bucket,
            key,
            tf_state_s3.region,
        )

    @staticmethod
    def _create_cloudflare_account_config(
        cf_acct: CloudflareAccount, secret_reader: SecretReaderBase
    ) -> CloudflareAccountConfig:
        cf_acct_creds = secret_reader.read_all_secret(cf_acct.api_credentials)
        cf_acct_config = CloudflareAccountConfig(
            cf_acct.name,
            cf_acct_creds["api_token"],
            cf_acct_creds["account_id"],
            cf_acct.enforce_twofactor or DEFAULT_CLOUDFLARE_ACCOUNT_2FA,
            cf_acct.type or DEFAULT_CLOUDFLARE_ACCOUNT_TYPE,
        )
        return cf_acct_config

    @classmethod
    def get_client(
        cls,
        tf_state_s3: TerraformStateS3,
        cf_acct: CloudflareAccount,
        sharding_strategy: TerraformS3StateNamingStrategy | None,
        secret_reader: SecretReaderBase,
        is_managed_account: bool,
        provider_rps: int = DEFAULT_PROVIDER_RPS,
    ) -> TerrascriptCloudflareClient:
        key = _get_terraform_s3_state_key_name(
            tf_state_s3.integration, sharding_strategy
        )
        backend_config = cls._create_backend_config(tf_state_s3, key, secret_reader)
        cf_acct_config = cls._create_cloudflare_account_config(cf_acct, secret_reader)
        ts_config = create_cloudflare_terrascript(
            cf_acct_config,
            backend_config,
            cf_acct.provider_version,
            provider_rps=provider_rps,
            is_managed_account=is_managed_account,
        )
        client = TerrascriptCloudflareClient(ts_config)
        return client


def _get_terraform_s3_state_key_name(
    integration: Integration,
    sharding_strategy: TerraformS3StateNamingStrategy | None,
) -> str:
    if sharding_strategy is None:
        sharding_strategy = Default()

    return sharding_strategy.get_object_key(integration)


class IntegrationUndefined(Exception):
    pass


class InvalidTerraformState(Exception):
    pass
