import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional

from terrascript import Terrascript, Terraform, Resource
from terrascript import provider

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.terrascript.cloudflare_resources import _CloudflareZoneResource

TMP_DIR_PREFIX = "terrascript-cloudflare-"


@dataclass
class CloudflareAccountConfig:
    name: str
    email: str
    api_key: str
    account_id: str


@dataclass
class S3BackendConfig:
    access_key: str
    secret_key: str
    bucket: str
    key: str
    region: str


def create_terrascript_cloudflare(
    account_config: CloudflareAccountConfig, backend_config: S3BackendConfig
) -> Terrascript:
    terrascript = Terrascript()

    terrascript += Terraform(
        required_providers={
            # TODO: pull this from account file
            "cloudflare": {"source": "cloudflare/cloudflare", "version": "3.18"}
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


class TerraformClient(ABC):
    """Early proposal, might decide to change dump() signature."""

    @abstractmethod
    def add_specs(self, specs: Iterable[ExternalResourceSpec]) -> None:
        ...

    @abstractmethod
    def populate_resources(self) -> None:
        ...

    @abstractmethod
    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dir: Optional[str] = None,
    ) -> None:
        ...

    @abstractmethod
    def dumps(self) -> str:
        ...


class TerrascriptCloudflareClient(TerraformClient):
    """
    Build the Terrascript configuration, collect resources, and return Terraform JSON
    configuration
    """

    def __init__(
        self,
        ts_client: Terrascript,
    ):
        self._terrascript = ts_client
        self._resource_specs: ExternalResourceSpecInventory = {}
        self._resource_classes = {"cloudflare_zone": _CloudflareZoneResource}

    def add_specs(self, specs: Iterable[ExternalResourceSpec]) -> None:
        for spec in specs:
            self._resource_specs[spec.id_object()] = spec

    def populate_resources(self) -> None:
        """
        Add the resource spec to Terrascript using the resource-specific classes
        to determine which resources to create.
        """
        for spec in self._resource_specs.values():
            resource_class = self._resource_classes[spec.provision_provider]
            resource = resource_class(spec)
            resources_to_add = resource.populate()
            self._add_resources(resources_to_add)

    def dump(
        self, print_to_file: Optional[str] = None, existing_dir: Optional[str] = None
    ) -> None:
        """Write the Terraform JSON representation of the resources to disk"""
        if existing_dir is None:
            temp_dir = tempfile.mkdtemp(prefix=TMP_DIR_PREFIX)
        else:
            temp_dir = existing_dir
        with open(temp_dir + "/config.tf.json", "w") as terraform_config_file:
            terraform_config_file.write(self.dumps())

    def dumps(self) -> str:
        """Return the Terraform JSON representation of the resources"""
        return str(self._terrascript)

    def _add_resources(self, tf_resources: Resource) -> None:
        for resource in tf_resources:
            self._terrascript.add(resource)


class TerrascriptCloudflareClientCollection:
    """
    Collection of TerracriptCloudflareClients for consolidating logic related to
    concurrency and common operations
    """

    def __init__(self):
        self._clients: set[TerrascriptCloudflareClient] = set()

    def register_client(self, client: TerrascriptCloudflareClient):
        self._clients.add(client)

    def init_populate_specs(self):
        pass

    def populate_resources(self):
        pass

    def dump(self):
        pass


def main():
    """
    All of this will go away, just a testing ground before all the schemas and accounts
    are set up.
    """

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
    backend_config = S3BackendConfig("abc", "abc", "some-bucket", "config", "us-east-1")

    terrascript_client = create_terrascript_cloudflare(account_config, backend_config)
    cloudflare_client = TerrascriptCloudflareClient(terrascript_client)

    # Dummy data for creating a Cloudflare zone object
    spec = ExternalResourceSpec(
        "cloudflare_zone",
        {"name": "dev", "automationToken": {}},
        {
            "provider": "cloudflare",
            "identifier": "domain-com",
            "zone": "domain.com",
            "plan": "enterprise",
            "type": "full",
        },
        {},
    )
    # Deviated from the Terrascript[Aws]Client by calling this add_specs() and just
    # dealing with ExternalResourceSpecs directly. We can deal with namespaces and call
    # it init_populate_specs() if determine that it's important enough to do so, and
    # if we decide this will be a single integration instead of a separate integration.
    cloudflare_client.add_specs([spec])
    cloudflare_client.populate_resources()

    cloudflare_client.dump()


if __name__ == "__main__":
    main()
