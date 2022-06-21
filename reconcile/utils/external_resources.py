from typing import Mapping, List, Any, Optional, Set

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
