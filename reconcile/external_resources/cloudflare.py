from abc import ABC, abstractmethod
from typing import Any

from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourcesInventory,
)
from reconcile.utils.exceptions import SecretIncompleteError
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.secret_reader import SecretReaderBase


class CloudflareResourceFactory(ABC):
    def __init__(
        self, er_inventory: ExternalResourcesInventory, secret_reader: SecretReaderBase
    ):
        self.er_inventory = er_inventory
        self.secret_reader = secret_reader

    @abstractmethod
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None: ...

    def find_linked_resources(
        self, spec: ExternalResourceSpec
    ) -> set[ExternalResourceKey]:
        """Method to find dependant resources. Resources in this list
        will be reconciled every time the parent resource finishes its reconciliation."""
        return set()


class CloudflareDefaultResourceFactory(CloudflareResourceFactory):
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        api_credentials = spec.provisioner["api_credentials"]
        creds = self.secret_reader.read_all(api_credentials)
        account_id = creds.get("account_id")
        if not account_id:
            raise SecretIncompleteError(
                f"secret {api_credentials['path']} incomplete: account_id missing"
            )
        resolved_values = ResourceValueResolver(
            spec=spec, identifier_as_value=True
        ).resolve()
        return resolved_values | {
            "account_id": account_id,
        }

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None: ...
