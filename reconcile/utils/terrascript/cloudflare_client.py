import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import (
    Optional,
    Union,
)

from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import AWSAccountV1, \
    CloudflareAccountV1
from reconcile.utils.models.models import CloudflareAccount, AWSAccount, TerraformStateS3, Integration

from reconcile.utils.secret_reader import SecretReader
from terrascript import (
    Backend,
    Output,
    Resource,
    Terraform,
    Terrascript,
    Variable,
    provider,
)

from reconcile import queries
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.terraform.config import TerraformS3BackendConfig
from reconcile.utils.terraform.config_client import TerraformConfigClient
from reconcile.utils.terrascript.cloudflare_resources import (
    cloudflare_account,
    create_cloudflare_terrascript_resource,
)

from abc import ABC, abstractmethod
from string import Template

TMP_DIR_PREFIX = "terrascript-cloudflare-"

DEFAULT_CLOUDFLARE_ACCOUNT_TYPE = "standard"
DEFAULT_CLOUDFLARE_ACCOUNT_2FA = False


@dataclass
class CloudflareAccountConfig:
    """Configuration related to authenticating API calls to Cloudflare."""

    name: str
    api_token: str
    account_id: str
    enforce_twofactor: bool = DEFAULT_CLOUDFLARE_ACCOUNT_2FA
    type: str = DEFAULT_CLOUDFLARE_ACCOUNT_TYPE


def create_cloudflare_terrascript(
        account_config: CloudflareAccountConfig,
        backend_config: TerraformS3BackendConfig,
        provider_version: str,
) -> Terrascript:
    """
    Configures a Terrascript class with the required provider(s) and backend
    configuration. This is offloaded to a separate function to avoid mixing additional
    logic into TerrascriptCloudflareClient.
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

    terrascript += Terraform(backend=backend, required_providers=required_providers)

    terrascript += provider.cloudflare(
        api_token=account_config.api_token,
        account_id=account_config.account_id,  # needed for some resources, see note below
    )

    cloudflare_account_values = {
        "name": account_config.name,
        "enforce_twofactor": account_config.enforce_twofactor,
        "type": account_config.type,
    }
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

    def dump(self, existing_dir: Optional[str] = None) -> str:
        """Write the Terraform JSON representation of the resources to disk"""
        if existing_dir is None:
            working_dir = tempfile.mkdtemp(prefix=TMP_DIR_PREFIX)
        else:
            working_dir = existing_dir
        with open(working_dir + "/config.tf.json", "w") as terraform_config_file:
            terraform_config_file.write(self.dumps())

        return working_dir

    def dumps(self) -> str:
        """Return the Terraform JSON representation of the resources"""
        return str(self._terrascript)

    def _add_resources(self, tf_resources: Iterable[Union[Resource, Output]]) -> None:
        for resource in tf_resources:
            self._terrascript.add(resource)


class S3ObjectKeyShardingStrategy(ABC):

    @abstractmethod
    def get_object_key(self, qr_integration) -> str:
        pass


class Default(S3ObjectKeyShardingStrategy):

    def get_object_key(self, qr_integration) -> str:
        return qr_integration


class TemplateBasedStrategy(S3ObjectKeyShardingStrategy):

    def get_object_key(self, qr_integration) -> str:
        pass


class AccountShardingStrategy(S3ObjectKeyShardingStrategy):

    def __init__(self, account):
        super().__init__()
        self.account: CloudflareAccount = account

    def get_bucket_key(self, qr_integration) -> str:
        return f"{qr_integration}-{self.account.name}.tfstate"


class TerrascriptCloudflareClientFactory:

    def __init__(self, secret_reader: SecretReader):
        self.secret_reader: SecretReader = secret_reader  # for reading aws creds for state

    def _create_backend_config(self, tf_state_s3: TerraformStateS3, key: str) -> TerraformS3BackendConfig:
        aws_acct_creds = self.secret_reader.read_all({"path": tf_state_s3.automation_token_path})

        return TerraformS3BackendConfig(aws_acct_creds["aws_access_key_id"],
                                        aws_acct_creds["aws_secret_access_key"],
                                        tf_state_s3.bucket,
                                        key,
                                        tf_state_s3.region)

    def _create_cloudflare_account_config(self, cf_acct: CloudflareAccount) -> CloudflareAccountConfig:
        cf_acct_creds = self.secret_reader.read_all({"path": cf_acct.api_credentials_path})
        cf_acct_config = CloudflareAccountConfig(
            cf_acct.name,
            cf_acct_creds["api_token"],
            cf_acct_creds["account_id"],
            cf_acct.enforce_twofactor or DEFAULT_CLOUDFLARE_ACCOUNT_2FA,
            cf_acct.type or DEFAULT_CLOUDFLARE_ACCOUNT_TYPE,
        )
        return cf_acct_config

    def create(self, qr_integration: str,
               tf_state_s3: TerraformStateS3,
               cf_acct: CloudflareAccount,
               sharding_strategy: S3ObjectKeyShardingStrategy) -> TerrascriptCloudflareClient:
        key = get_s3_object_key(qr_integration, tf_state_s3, sharding_strategy)
        backend_config = self._create_backend_config(tf_state_s3, key)
        cf_acct_config = self._create_cloudflare_account_config(cf_acct)
        ts_config = create_cloudflare_terrascript(cf_acct_config, backend_config, cf_acct.provider_version)
        client = TerrascriptCloudflareClient(ts_config)
        return client


def get_s3_object_key(qr_integration: str, tf_state_s3: TerraformStateS3,
                      sharding_strategy: S3ObjectKeyShardingStrategy):
    integrations = tf_state_s3.integrations or []
    if qr_integration not in [i.name.replace("-", "_") for i in integrations]:
        raise ValueError('Must declare integration name under terraform state in app-interface')

    for i in integrations or []:
        name = i.integration
        if name.replace("-", "_") == qr_integration:
            return sharding_strategy.get_object_key(i.key)


def use():
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    factory = TerrascriptCloudflareClientFactory(secret_reader)

    accounts: Optional[list[CloudflareAccountV1]] = None

    for account in accounts:
        cf_account = CloudflareAccount(account.name,
                                       account.api_credentials.path,
                                       account.enforce_twofactor,
                                       account.q_type,
                                       account.provider_version)

        tf_state_s3 = TerraformStateS3(account.terraform_state_account.automation_token.path,
                                       account.terraform_state_account.terraform_state.bucket,
                                       account.terraform_state_account.terraform_state.region,
                                       [Integration(i.integration, i.key) for i in
                                        account.terraform_state_account.terraform_state.integrations])

        factory.create('qr-integration', tf_state_s3, cf_account,
                       AccountShardingStrategy(cf_account))
