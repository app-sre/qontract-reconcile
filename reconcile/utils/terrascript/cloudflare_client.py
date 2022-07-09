import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Iterable, Optional, Union
from unittest.mock import MagicMock

from terrascript import Terrascript, Terraform, Resource, Output
from terrascript import provider

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.terraform.config import TerraformS3BackendConfig
from reconcile.utils.terraform.config_client import (
    TerraformConfigClient,
    TerraformConfigClientCollection,
)
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript.cloudflare_resources import (
    create_cloudflare_terrascript_resource,
)

TMP_DIR_PREFIX = "terrascript-cloudflare-"


@dataclass
class CloudflareAccountConfig:
    """Configuration related to authenticating API calls to Cloudflare."""

    name: str
    email: str
    api_key: str
    account_id: str


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

    terrascript += Terraform(
        required_providers={
            "cloudflare": {
                "source": "cloudflare/cloudflare",
                "version": provider_version,
            }
        }
    )

    terrascript += provider.cloudflare(
        email=account_config.email,
        api_key=account_config.api_key,
        account_id=account_config.account_id,
    )

    """
    backend = Backend(
        "s3",
        access_key=backend_config.access_key,
        secret_key=backend_config.secret_key,
        bucket=backend_config.bucket,
        key=backend_config.key,
        region=backend_config.region,
    )
    """

    # terrascript += Terraform(backend=backend)

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
    ):
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

    def dump(
        self, print_to_file: Optional[str] = None, existing_dir: Optional[str] = None
    ) -> str:
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


def main():  # pragma: no cover
    """
    All of this will go away, just a testing ground before the decision is made whether
    this is a standalone integration or not, as well as schemas/gql queries
    """

    logging.basicConfig(level=logging.INFO)

    # This account config will be in Vault and come from the cloudflare/account-1.yml
    # schema.
    account_config = CloudflareAccountConfig(
        "dev",
        os.environ["EMAIL"],
        os.environ["API_TOKEN"],
        os.environ["ACCOUNT_ID"],
    )

    # Dummy backend config for now, not actually being used, but would again come from
    # account config like with AWS resources.
    backend_config = TerraformS3BackendConfig(
        "abc", "abc", "some-bucket", "config", "us-east-1"
    )

    # TODO: get this from account config
    cloudflare_provider_version = "3.18"

    terrascript_client_a = create_cloudflare_terrascript(
        account_config, backend_config, cloudflare_provider_version
    )

    terrascript_client_b = create_cloudflare_terrascript(
        account_config, backend_config, cloudflare_provider_version
    )

    # Dummy data for two separate accounts just to show how TerrascriptCloudflareClientCollection
    # would work. This data would all actually come from app-interface from calls in the
    # terraform-resources-cloudflare integration if that path is agreed upon.
    acct_a_cloudflare_client = TerrascriptCloudflareClient(terrascript_client_a)
    acct_a_specs = [
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "acct_a", "automationToken": {}},
            {
                "provider": "cloudflare",
                "identifier": "acct-a-domain-com",
                "zone": "acct-a.domain.com",
                "plan": "free",
                "type": "full",
            },
            {},
        )
    ]

    acct_b_cloudflare_client = TerrascriptCloudflareClient(terrascript_client_b)
    acct_b_specs = [
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "acct_b", "automationToken": {}},
            {
                "provider": "cloudflare",
                "identifier": "acct-b-domain-com",
                "zone": "acct-b.domain.com",
                "plan": "enterprise",
                "type": "partial",
            },
            {},
        )
    ]

    # Deviated from the Terrascript[Aws]Client by calling this add_specs() and just
    # dealing with ExternalResourceSpecs directly. We can deal with namespaces and call
    # it init_populate_specs() if determine that it's important enough to do so, and
    # if we decide this will be a single integration instead of a separate integration.
    cloudflare_clients = TerraformConfigClientCollection()
    cloudflare_clients.register_client("acct_a", acct_a_cloudflare_client)
    cloudflare_clients.register_client("acct_b", acct_b_cloudflare_client)
    cloudflare_clients.add_specs(acct_a_specs + acct_b_specs)
    cloudflare_clients.populate_resources()
    working_dirs = cloudflare_clients.dump()

    QONTRACT_INTEGRATION = "terraform_resources_cloudflare"
    QONTRACT_INTEGRATION_VERSION = "0.5.2"
    QONTRACT_TF_PREFIX = "qrtf"

    # TerraformClient has some AWS-specific logic in it that we can probably factor out.
    # Most of it seems to have to do with log_plan_diff and figuring out whether to
    # apply or not.
    tf = TerraformClient(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        [{"name": "acct_a"}, {"name": "acct_b"}],
        working_dirs,
        1,
        MagicMock(),
    )

    # Uncomment to run plan
    # tf.plan(False)

    tf.cleanup()


if __name__ == "__main__":  # pragma: no cover
    main()
