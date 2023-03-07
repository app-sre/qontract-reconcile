import pytest

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terrascript.cloudflare_resources import (
    UnsupportedCloudflareResourceError,
    create_cloudflare_terrascript_resource,
)


def create_external_resource_spec(provision_provider):
    return ExternalResourceSpec(
        provision_provider=provision_provider,
        provisioner={"name": "dev", "automationToken": {}},
        resource={
            "provider": provision_provider,
            "identifier": "test",
        },
        namespace={},
    )


def test_create_cloudflare_terrascript_resource_unsupported():
    spec = create_external_resource_spec("doesntexist")

    with pytest.raises(UnsupportedCloudflareResourceError):
        create_cloudflare_terrascript_resource(spec)
