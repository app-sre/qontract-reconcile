from typing import Union

from terrascript import Resource, Output
from terrascript.resource import (
    cloudflare_zone,
    cloudflare_zone_settings_override,
    cloudflare_record,
    cloudflare_worker_route,
    cloudflare_worker_script,
)
from reconcile import queries

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.github_api import GithubApi
from reconcile.utils.terrascript.resources import TerrascriptResource
from reconcile.utils.terrascript_aws_client import safe_resource_id


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

    if resource_type == "cloudflare_zone":
        return CloudflareZoneTerrascriptResource(spec).populate()
    else:
        raise UnsupportedCloudflareResourceError(
            f"The resource type {resource_type} is not supported"
        )


class CloudflareZoneTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_zone and related resources."""

    def populate(self) -> list[Union[Resource, Output]]:

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})
        zone_records = values.pop("records", [])
        zone_workers = values.pop("workers", [])

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

        records = []
        for rec in zone_records:
            record_identifier = safe_resource_id(rec.get("name"))
            record_values = {
                "zone_id": f"${{{zone.id}}}",
                "depends_on": self._get_dependencies([zone]),
                "type": rec.pop("q_type"),
                **rec,
            }
            records.append(cloudflare_record(record_identifier, **record_values))

        workers = []
        worker_scripts = []
        for wrk in zone_workers:
            wrk_script = wrk.get("script")

            gh_repo = wrk_script["content_from_github"]["repo"]
            gh_path = wrk_script["content_from_github"]["path"]
            gh_ref = wrk_script["content_from_github"]["ref"]
            gh = GithubApi(
                queries.get_github_instance(),
                gh_repo,
                queries.get_app_interface_settings(),
            )
            content = gh.get_file(gh_path, gh_ref)
            if content is None:
                raise ValueError(
                    f"Could not retrieve Github file content at {gh_repo} "
                    f"for file path {gh_path} at ref {gh_ref}"
                )
            wrk_content = content.decode(encoding="utf-8")

            worker_script_values = {
                "name": wrk_script.get("name"),
                "content": wrk_content,
            }
            worker_script_resource = cloudflare_worker_script(
                safe_resource_id(wrk_script.get("name")), **worker_script_values
            )
            worker_scripts.append(worker_script_resource)

            worker_route_values = {
                "pattern": wrk.get("pattern"),
                "script_name": worker_script_resource.name,
                "zone_id": f"${{{zone.id}}}",
                "depends_on": self._get_dependencies([worker_script_resource]),
            }
            workers.append(
                cloudflare_worker_route(
                    safe_resource_id(wrk.get("identifier")), **worker_route_values
                )
            )
        return [zone, zone_settings_override, *records, *workers, *worker_scripts]
