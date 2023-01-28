import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import (
    Optional,
    Union,
)

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


ZONE_STRATEGY = 'zone'
ACCOUNT_STRATEGY = 'account'
SHARDING_STRATEGY = [ZONE_STRATEGY, ACCOUNT_STRATEGY]


class TerrascriptCloudflareClientFactory(ABC):

    # aws_acct is a dependency because we decided to store state in aws s3 for terraform. TBD if this needs to be
    # optional to support local state. currently, out of scope for now.

    # need dataclasses for aws_acct and cf_acct, separate from query classes.
    def __init__(self, secret_reader, aws_acct, provider_version, cf_acct):
        self.secret_reader = secret_reader  # for reading aws creds for state
        self.aws_acct = aws_acct  # contains state
        self.provider_version = provider_version
        self.bucket_key = None
        self.cf_acct = cf_acct
        self.QONTRACT_INTEGRATION = None
        self.sharding_strategy = None
        # Optional vars
        self.zone = None
        pass

    def set_sharding_strategy(self, sharding_strategy: str):

        if sharding_strategy not in SHARDING_STRATEGY:
            raise ValueError('Incorrect value')

        self.sharding_strategy = sharding_strategy

    def set_zone(self, zone):
        '''zone is ignored if sharding strategy is account'''
        self.zone = zone

    def set_qr_integration_name(self, name):
        self.QONTRACT_INTEGRATION = name

    def _validate(self):
        if self.QONTRACT_INTEGRATION is None:
            raise ValueError('Must set this')

        if self.sharding_strategy == 'zone':
            if self.zone is None:
                raise ValueError('Must set this')

    def _create_backend_config(self) -> TerraformS3BackendConfig:

        def _get_bucket_key_based_on_sharding_strategy():
            if self.sharding_strategy == ZONE_STRATEGY:
                return f"{self.QONTRACT_INTEGRATION}-{self.cf_acct.name}{self.zone}.tfstate"
            elif self.sharding_strategy == ACCOUNT_STRATEGY:
                return f"{self.QONTRACT_INTEGRATION}-{self.cf_acct.name}.tfstate"

        if self.bucket_key is None:
            raise ValueError('Incomplete data...')

        # default from AWS account file
        tf_state = self.aws_acct.terraform_state
        if tf_state is None:
            raise ValueError(
                f"AWS account {self.aws_acct.name} cannot be used for Cloudflare "
                f"account {self.cf_acct.name} because it does define a terraform state "
            )

        integrations = tf_state.integrations or []
        if self.QONTRACT_INTEGRATION not in [i.name.replace("-", "_") for i in integrations]:
            raise ValueError('Must declare integration name under terraform state in app-interface')

        self.bucket_key = _get_bucket_key_based_on_sharding_strategy()

        if tf_state.bucket and self.bucket_key and tf_state.region:
            aws_acct_creds = self.secret_reader.read_all({"path": self.aws_acct.automation_token.path})
            backend_config = TerraformS3BackendConfig(
                aws_acct_creds["aws_access_key_id"],
                aws_acct_creds["aws_secret_access_key"],
                tf_state.bucket,
                self.bucket_key,
                tf_state.region,
            )
        else:
            # Alternatively, could expand to utilize local state on filesystem...
            raise ValueError(f"No state bucket config found for account {self.aws_acct.name}")

        return backend_config

    def _create_cloudflare_account_config(self) -> CloudflareAccountConfig:

        cf_acct_creds = self.secret_reader.read_all({"path": self.cf_acct.api_credentials.path})
        cf_acct_config = CloudflareAccountConfig(
            self.cf_acct.name,
            cf_acct_creds["api_token"],
            cf_acct_creds["account_id"],
            self.cf_acct.enforce_twofactor or DEFAULT_CLOUDFLARE_ACCOUNT_2FA,
            self.cf_acct.q_type or DEFAULT_CLOUDFLARE_ACCOUNT_TYPE,
        )
        return cf_acct_config

    def create(self) -> TerrascriptCloudflareClient:
        self._validate()
        backend_config = self._create_backend_config()
        cf_acct_config = self._create_cloudflare_account_config()
        ts_config = create_cloudflare_terrascript(cf_acct_config, backend_config, self.provider_version)
        client = TerrascriptCloudflareClient(ts_config)
        return client


def use():
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    account_bldr = TerrascriptCloudflareClientFactory()
    account_bldr.sharding_strategy(ACCOUNT)
