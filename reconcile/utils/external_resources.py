import json
from collections import Counter
from collections.abc import Mapping, MutableMapping
from typing import Any

import anymarkup

from reconcile.external_resources.model import ExternalResourcesInventory
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.external_resource_spec import (
    ExternalResourceInventoryGauge,
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)

PROVIDER_AWS = "aws"
PROVIDER_CLOUDFLARE = "cloudflare"


def get_external_resource_specs(
    namespace_info: Mapping[str, Any],
    provision_provider: str | None = None,
) -> list[ExternalResourceSpec]:
    specs: list[ExternalResourceSpec] = []
    if not managed_external_resources(namespace_info):
        return specs

    external_resources = namespace_info.get("externalResources") or []
    for e in external_resources:
        for r in e.get("resources", []):
            spec = ExternalResourceSpec(
                provision_provider=e["provider"],
                provisioner=e["provisioner"],
                resource=r,
                namespace=namespace_info,
            )
            specs.append(spec)

    if provision_provider:
        specs = [s for s in specs if s.provision_provider == provision_provider]

    return specs


def get_provision_providers(namespace_info: Mapping[str, Any]) -> set[str]:
    providers: set[str] = set()
    if not managed_external_resources(namespace_info):
        return providers

    external_resources = namespace_info.get("externalResources") or []
    providers.update(e["provider"] for e in external_resources)

    return providers


def managed_external_resources(namespace_info: Mapping[str, Any]) -> bool:
    return bool(namespace_info.get("managedExternalResources"))


def get_inventory_count_combinations(
    inventory: ExternalResourceSpecInventory | ExternalResourcesInventory,
) -> Counter[tuple]:
    return Counter(
        (k.provision_provider, k.provisioner_name, k.provider) for k in inventory
    )


def publish_metrics(
    inventory: ExternalResourceSpecInventory | ExternalResourcesInventory,
    integration: str,
) -> None:
    count_combinations = get_inventory_count_combinations(inventory)
    integration_name = metrics.normalize_integration_name(integration)
    for combination, count in count_combinations.items():
        provision_provider, provisioner_name, provider = combination
        metrics.set_gauge(
            ExternalResourceInventoryGauge(
                integration=integration_name,
                provision_provider=provision_provider,
                provisioner_name=provisioner_name,
                provider=provider,
            ),
            count,
        )


class ResourceValueResolver:
    """
    ExternalResourceSpec have data that's contained in different fields including the
    base "resources" data, as well as "overrides" and "defaults" that need to be
    resolved to get the final data set. This is meant to consolidate that logic and
    produce the final set of data for provisioning resources.

    All of this logic was extracted from TerrascriptClient with some minor changes
    related to replacing VARIABLE_KEYS with _IGNORE_KEYS to go with an exclusion
    approach rather than needing to manually update a list every time we use a new
    field. Once this is locked in a bit better, we can remove all of these methods from
    TerrascriptClient.
    """

    # _IGNORE_KEYS represents the fields that are specific to our schemas. These are not
    # need to create Terraform resources. The only exception is `identifier` which is
    # used in more than one way (see identifier_as_value below).
    #
    # Before we were taking a different approach where an inclusion list of variables
    # was being maintained that had 35+ entries. It should be simpler to exclude
    # instead.
    _IGNORE_KEYS = {"identifier", "defaults", "overrides", "provider"}

    def __init__(
        self,
        spec: ExternalResourceSpec,
        integration_tag: str | None = None,
        identifier_as_value: bool = False,
    ):
        """
        :param spec: external resource spec
        :param integration_tag: optionally tag the resource with an integration name
        :param identifier_as_value: `identifier` is both used in the external resource
                                    schema as the resource name and in addition, some
                                    Terraform providers (like AWS) also expect an
                                    `identifier` argument. Only set this to true if the
                                    provider expects an `identifier` argument.
        """
        self._spec = spec
        self._integration_tag = integration_tag
        self._identifier_as_value = identifier_as_value

    def resolve(self) -> dict:
        """
        Resolves the final set of values after aggregating and overriding values.
        """
        resource = self._spec.resource

        keys_to_add = [
            key for key in self._spec.resource if key not in self._IGNORE_KEYS
        ]

        defaults_path = resource.get("defaults", None)
        overrides = resource.get("overrides", None)

        # TODO: see Gerd's example in https://issues.redhat.com/browse/APPSRE-6003 and
        # just handle the defaults values directly. This isn't a blocker for the initial
        # PR because it needs to be updated on the integration side.
        values = self._get_values(defaults_path) if defaults_path else {}
        self._aggregate_values(values)
        self._override_values(values, overrides)

        if self._identifier_as_value:
            values["identifier"] = self._spec.identifier

        if self._integration_tag:
            values["tags"] = self._spec.tags(self._integration_tag)

        for key in keys_to_add:
            val = resource.get(key, None)
            # checking explicitly for not None
            # to allow passing empty strings, False, etc
            if val is not None:
                values[key] = val

        return values

    def _get_values(self, path: str) -> dict:
        raw_values = self._get_raw_values(path)
        try:
            values = anymarkup.parse(raw_values["content"], force_types=None)
            values.pop("$schema", None)
        except anymarkup.AnyMarkupError:
            e_msg = "Could not parse data. Skipping resource: {}"
            raise FetchResourceError(e_msg.format(path)) from None
        return values

    @staticmethod
    def _get_raw_values(path: str) -> dict[str, str]:
        gqlapi = gql.get_api()
        try:
            raw_values = gqlapi.get_resource(path)
        except gql.GqlGetResourceError as e:
            raise FetchResourceError(str(e)) from e
        return raw_values

    @staticmethod
    def _aggregate_values(values: dict[str, Any]) -> None:
        split_char = "."
        copy = values.copy()
        for k, v in copy.items():
            if split_char not in k:
                continue
            k_split = k.split(split_char)
            primary_key = k_split[0]
            secondary_key = k_split[1]
            values.setdefault(primary_key, {})
            values[primary_key][secondary_key] = v
            values.pop(k, None)

    @staticmethod
    def _override_values(
        values: MutableMapping[str, Any], overrides: str | None
    ) -> None:
        if overrides is None:
            return
        data = json.loads(overrides)
        for k, v in data.items():
            values[k] = v
