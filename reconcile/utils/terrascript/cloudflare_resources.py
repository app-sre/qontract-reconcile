from typing import Union

from terrascript import Resource, Output
from terrascript.resource import (
    cloudflare_argo,
    cloudflare_zone,
    cloudflare_zone_settings_override,
    cloudflare_record,
    cloudflare_worker_route,
    cloudflare_worker_script,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.terrascript.resources import TerrascriptResource


class UnsupportedCloudflareResourceError(Exception):
    pass


def create_cloudflare_terrascript_resource(
    spec: ExternalResourceSpec,
) -> list[Union[Resource, Output]]:
    """
    Create the required Cloudflare Terrascript resources as defined by the external
    resources spec.
    """
    resource_type = spec.provision_provider

    if resource_type == "cloudflare_argo":
        return CloudflareArgoTerrascriptResource(spec).populate()
    elif resource_type == "cloudflare_record":
        return CloudflareRecordTerrascriptResource(spec).populate()
    elif resource_type == "cloudflare_worker":
        return CloudflareWorkerTerrascriptResource(spec).populate()
    elif resource_type == "cloudflare_zone":
        return CloudflareZoneTerrascriptResource(spec).populate()
    else:
        raise UnsupportedCloudflareResourceError(
            f"The resource type {resource_type} is not supported"
        )


class CloudflareArgoTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_argo."""

    def populate(self) -> list[Union[Resource, Output]]:
        values = ResourceValueResolver(self._spec).resolve()
        return [cloudflare_argo(self._spec.identifier, **values)]


class CloudflareRecordTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_record."""

    def populate(self) -> list[Union[Resource, Output]]:
        values = ResourceValueResolver(self._spec).resolve()
        return [cloudflare_record(self._spec.identifier, **values)]


class CloudflareWorkerTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_worker and related resources."""

    def populate(self) -> list[Union[Resource, Output]]:
        values = ResourceValueResolver(self._spec).resolve()

        worker_script_name = values.pop("script_name")
        worker_script_content = values.pop("script_content")
        worker_script_vars = values.pop("script_vars")

        worker_values = {"script_name": worker_script_name, **values}

        worker_resource = cloudflare_worker_route(
            self._spec.identifier, **worker_values
        )

        worker_script_values = {
            "depends_on": self._get_dependencies([worker_resource]),
            "name": worker_script_name,
            "content": worker_script_content,
            "plain_text_binding": worker_script_vars,
        }
        worker_script_resource = cloudflare_worker_script(
            self._spec.identifier, **worker_script_values
        )

        return [
            worker_resource,
            worker_script_resource,
        ]


class CloudflareZoneTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_zone and related resources."""

    def populate(self) -> list[Union[Resource, Output]]:
        resources = []

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})

        zone_values = values
        zone = cloudflare_zone(self._spec.identifier, **zone_values)
        resources.append(zone)

        settings_override_values = {
            "zone_id": f"${{{zone.id}}}",
            "settings": zone_settings,
            "depends_on": self._get_dependencies([zone]),
        }

        zone_settings_override = cloudflare_zone_settings_override(
            self._spec.identifier, **settings_override_values
        )
        resources.append(zone_settings_override)

        return resources
