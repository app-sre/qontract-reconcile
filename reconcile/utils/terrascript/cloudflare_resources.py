from abc import ABC, abstractmethod

from terrascript.resource import cloudflare_zone, cloudflare_zone_settings_override

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver


class _CloudflareResource(ABC):
    """Early proposal, might decide to change method names"""

    def __init__(self, spec: ExternalResourceSpec):
        self._spec = spec

    @abstractmethod
    def populate(self):
        ...


class _CloudflareZoneResource(_CloudflareResource):
    """
    Translate from the cloudflare_zone provider ExternalResourceSpec to resulting
    Terrascript resource objects.
    """

    def populate(self):

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})

        zone_values = values
        zone = cloudflare_zone(self._spec.identifier, **zone_values)

        settings_override_values = {
            "zone_id": f"${{{zone.id}}}",
            "settings": zone_settings,
        }

        zone_settings_override = cloudflare_zone_settings_override(
            self._spec.identifier, **settings_override_values
        )

        return [zone, zone_settings_override]
