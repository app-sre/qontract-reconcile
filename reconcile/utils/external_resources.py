import json
from typing import Mapping, List, Any, Optional, Set

import anymarkup

from reconcile.utils import gql
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.external_resource_spec import ExternalResourceSpec


PROVIDER_AWS = "aws"


def get_external_resource_specs(
    namespace_info: Mapping[str, Any], provision_provider: Optional[str] = None
) -> List[ExternalResourceSpec]:
    specs: List[ExternalResourceSpec] = []
    if not managed_external_resources(namespace_info):
        return specs

    external_resources = namespace_info.get("externalResources") or []
    for e in external_resources:
        for r in e["resources"]:
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


def get_provision_providers(namespace_info: Mapping[str, Any]) -> Set[str]:
    providers: Set[str] = set()
    if not managed_external_resources(namespace_info):
        return providers

    external_resources = namespace_info.get("externalResources") or []
    for e in external_resources:
        providers.add(e["provider"])

    return providers


def managed_external_resources(namespace_info: Mapping[str, Any]) -> bool:
    if namespace_info.get("managedExternalResources"):
        return True

    return False


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

    # These are keys that don't need to make it to the resource creation. identifier is
    # already available via spec.identifier, defaults and overrides are values that we
    # merge with the others, and provider is available via spec.provider.
    #
    # Before we were taking a different approach where an inclusion list of variables
    # was being maintained that had 35+ entries. It should be simpler to exclude
    # instead.
    _IGNORE_KEYS = {"identifier", "defaults", "overrides", "provider"}

    def __init__(self, spec: ExternalResourceSpec, integration: Optional[str] = None):
        self._spec = spec
        self._integration = integration

    def resolve(self) -> dict:
        """
        Resolves the final set of values after aggregating and overriding values.
        """
        resource = self._spec.resource

        keys_to_add = [
            key for key in self._spec.resource.keys() if key not in self._IGNORE_KEYS
        ]

        defaults_path = resource.get("defaults", None)
        overrides = resource.get("overrides", None)

        values = self._get_values(defaults_path) if defaults_path else {}
        self._aggregate_values(values)
        self._override_values(values, overrides)
        # Do we really need the identifier if it's already available via spec?
        # values["identifier"] = self._spec.identifier

        if self._integration:
            values["tags"] = self._spec.tags(self._integration)

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
            raise FetchResourceError(e_msg.format(path))
        return values

    @staticmethod
    def _get_raw_values(path):
        gqlapi = gql_client.get_api()
        try:
            raw_values = gqlapi.get_resource(path)
        except gql_client.GqlGetResourceError as e:
            raise FetchResourceError(str(e))
        return raw_values

    @staticmethod
    def _aggregate_values(values):
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
    def _override_values(values, overrides):
        if overrides is None:
            return
        data = json.loads(overrides)
        for k, v in data.items():
            values[k] = v
