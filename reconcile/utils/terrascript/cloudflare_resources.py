from abc import ABC, abstractmethod
from typing import Iterable

from terrascript import Resource
from terrascript.resource import cloudflare_zone, cloudflare_zone_settings_override

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver


class _CloudflareResource(ABC):
    """Early proposal, might decide to change method names"""

    def __init__(self, spec: ExternalResourceSpec):
        self._spec = spec

    @staticmethod
    def _get_dependencies(tf_resources: Iterable[Resource]) -> list[str]:
        return [
            f"{tf_resource.__class__.__name__}.{tf_resource._name}"
            for tf_resource in tf_resources
        ]

    @abstractmethod
    def populate(self) -> list[Resource]:
        ...


class _CloudflareZoneResource(_CloudflareResource):
    """
    Translate from the cloudflare_zone provider ExternalResourceSpec to resulting
    Terrascript resource objects.
    """

    def populate(self) -> list[Resource]:

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})

        zone_values = values
        zone = cloudflare_zone(self._spec.identifier, **zone_values)

        settings_override_values = {
            "zone_id": f"${{{zone.id}}}",
            "settings": zone_settings,
            "depends_on": self._get_dependencies([zone]),
        }

        zone_settings_override = cloudflare_zone_settings_override(
            self._spec.identifier, **settings_override_values
        )

        return [zone, zone_settings_override]
