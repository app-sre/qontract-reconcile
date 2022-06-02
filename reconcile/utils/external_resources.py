from typing import Mapping, List, Dict, Any, Optional, Set


PROVIDER_AWS = "aws"


def get_external_resources(
    namespace_info: Mapping[str, Any], provision_provider: Optional[str] = None
) -> List[Dict[str, Any]]:
    resources: List[Dict[str, Any]] = []
    if not managed_external_resources(namespace_info):
        return resources

    terraform_resources = namespace_info.get("terraformResources") or []
    for r in terraform_resources:
        r["provision_provider"] = PROVIDER_AWS
        resources.append(r)

    external_resources = namespace_info.get("externalResources") or []
    for e in external_resources:
        provisioner_name = e["provisioner"]["name"]
        for r in e["resources"]:
            r["provision_provider"] = e["provider"]
            r["account"] = provisioner_name
            resources.append(r)

    if provision_provider:
        resources = [
            r for r in resources if r["provision_provider"] == provision_provider
        ]

    return resources


def get_provision_providers(namespace_info: Mapping[str, Any]) -> Set[str]:
    providers: Set[str] = set()
    if not managed_external_resources(namespace_info):
        return providers

    terraform_resources = namespace_info.get("terraformResources")
    if terraform_resources:
        providers.add(PROVIDER_AWS)

    external_resources = namespace_info.get("externalResources") or []
    for e in external_resources:
        providers.add(e["provider"])

    return providers


def managed_external_resources(namespace_info: Mapping[str, Any]) -> bool:
    if namespace_info.get("managedTerraformResources"):
        return True
    if namespace_info.get("managedExternalResources"):
        return True

    return False
