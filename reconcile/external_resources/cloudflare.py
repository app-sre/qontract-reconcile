import json
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


def get_account_id(
    secret_reader: SecretReaderBase, api_credentials: dict[str, Any]
) -> str:
    creds = secret_reader.read_all(api_credentials)
    account_id = creds.get("account_id")
    if not account_id:
        raise SecretIncompleteError(
            f"secret {api_credentials['path']} incomplete: account_id missing"
        )
    return account_id


class CloudflareDefaultResourceFactory(CloudflareResourceFactory):
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        account_id = get_account_id(
            self.secret_reader,
            spec.provisioner["api_credentials"],
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


class CloudflareZoneFactory(CloudflareResourceFactory):
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        account_id = get_account_id(
            self.secret_reader,
            spec.provisioner["api_credentials"],
        )
        resolved_values = ResourceValueResolver(
            spec=spec, identifier_as_value=True
        ).resolve()
        rulesets = [
            self._resolve_ruleset(ruleset)
            for ruleset in resolved_values.get("rulesets") or []
        ]
        return resolved_values | {
            "account_id": account_id,
            "rulesets": rulesets,
        }

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None: ...

    def _resolve_ruleset(self, ruleset: dict[str, Any]) -> dict[str, Any]:
        rules = ruleset.get("rules", [])
        return ruleset | {"rules": [self._resolve_rule(rule) for rule in rules]}

    @staticmethod
    def _resolve_rule(rule: dict[str, Any]) -> dict[str, Any]:
        action_parameters = rule.get("action_parameters")
        if not action_parameters:
            return rule
        return rule | {"action_parameters": json.loads(action_parameters)}
