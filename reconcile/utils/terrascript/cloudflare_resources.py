from collections.abc import (
    Iterable,
    MutableMapping,
)
from typing import (
    Any,
    Union,
)

from terrascript import (
    Output,
    Resource,
    Variable,
)
from terrascript.resource import (
    cloudflare_argo,
    cloudflare_record,
    cloudflare_worker_route,
    cloudflare_worker_script,
    cloudflare_zone,
    cloudflare_zone_settings_override,
)

from reconcile import queries
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.github_api import GithubApi
from reconcile.utils.terraform import safe_resource_id
from reconcile.utils.terrascript.resources import TerrascriptResource


class UnsupportedCloudflareResourceError(Exception):
    pass


class cloudflare_account(Resource):
    """
    https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/account
    This resource isn't supported directly by Terrascript, which is why it needs to be
    defined like this as a Resource.
    """


class cloudflare_certificate_pack(Resource):
    """
    https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/certificate_pack

    This resource isn't supported directly by Terrascript, which is why it needs to be
    defined like this as a Resource.
    """


def create_cloudflare_terrascript_resource(
    spec: ExternalResourceSpec,
) -> list[Union[Resource, Output]]:
    """
    Create the required Cloudflare Terrascript resources as defined by the external
    resources spec.
    """
    resource_type = spec.provider

    if resource_type == "worker_script":
        return CloudflareWorkerScriptTerrascriptResource(spec).populate()
    elif resource_type == "zone":
        return CloudflareZoneTerrascriptResource(spec).populate()
    else:
        raise UnsupportedCloudflareResourceError(
            f"The resource type {resource_type} is not supported"
        )


class CloudflareWorkerScriptTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_worker_script resource"""

    def populate(self) -> list[Union[Resource, Output]]:
        values = ResourceValueResolver(self._spec).resolve()

        gh_repo = values["content_from_github"]["repo"]
        gh_path = values["content_from_github"]["path"]
        gh_ref = values["content_from_github"]["ref"]
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

        name = values["name"]
        identifier = safe_resource_id(name)

        worker_script_content = Variable(
            f"{identifier}_content",
            type="string",
            default=content.decode(encoding="utf-8"),
        )

        worker_script_values = {
            "name": name,
            "content": f"${{var.{identifier}_content}}",
            "plain_text_binding": values.pop("vars"),
        }
        return [
            cloudflare_worker_script(identifier, **worker_script_values),
            worker_script_content,
        ]


class CloudflareZoneTerrascriptResource(TerrascriptResource):
    """Generate a cloudflare_zone and related resources."""

    def _create_cloudflare_certificate_pack(
        self, zone: Resource, zone_certs: Iterable[MutableMapping[str, Any]]
    ) -> list[Union[Resource, Output]]:
        resources = []
        for cert_values in zone_certs:
            identifier = safe_resource_id(cert_values.pop("identifier"))
            zone_cert_values = {
                "zone_id": f"${{{zone.id}}}",
                "depends_on": self._get_dependencies([zone]),
                **cert_values,
            }
            resources.append(
                cloudflare_certificate_pack(identifier, **zone_cert_values)
            )

        return resources

    def populate(self) -> list[Union[Resource, Output]]:
        resources = []

        values = ResourceValueResolver(self._spec).resolve()

        zone_settings = values.pop("settings", {})
        zone_argo = values.pop("argo", None)
        zone_records = values.pop("records", [])
        zone_workers = values.pop("workers", [])
        zone_certs = values.pop("certificates", [])

        zone_values = {
            "account_id": "${var.account_id}",
            **values,
        }
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

        if zone_argo is not None:
            # Terraform accepts "on" and "off" as values. However our data comes from a
            # YAML 1.1 implementation that turns the strings "on" and "off" into True and
            # False booleans so we must convert them back.
            # See: https://stackoverflow.com/a/42284910
            for k in ("smart_routing", "tiered_caching"):
                if k in zone_argo:
                    zone_argo[k] = "on" if zone_argo[k] is True else "off"

            argo_values = {
                "zone_id": f"${{{zone.id}}}",
                "depends_on": self._get_dependencies([zone]),
                **zone_argo,
            }

            resources.append(cloudflare_argo(self._spec.identifier, **argo_values))

        for record in zone_records:
            identifier = safe_resource_id(record.get("name"))
            record_values = {
                "zone_id": f"${{{zone.id}}}",
                "depends_on": self._get_dependencies([zone]),
                **record,
            }
            resources.append(cloudflare_record(identifier, **record_values))

        for worker in zone_workers:
            identifier = safe_resource_id(worker.pop("identifier"))
            worker_route_values = {
                "zone_id": f"${{{zone.id}}}",
                **worker,
            }
            resources.append(cloudflare_worker_route(identifier, **worker_route_values))

        resources.extend(self._create_cloudflare_certificate_pack(zone, zone_certs))

        return resources
