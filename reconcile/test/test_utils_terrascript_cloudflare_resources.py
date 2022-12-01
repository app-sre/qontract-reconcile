import pytest

from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terrascript.cloudflare_resources import (
    UnsupportedCloudflareResourceError,
    create_cloudflare_terrascript_resource,
)


def create_external_resource_spec(provision_provider):
    return ExternalResourceSpec(
        provision_provider,
        {"name": "dev", "automationToken": {}},
        {
            "provider": provision_provider,
            "identifier": "test",
        },
        {},
    )


def test_create_cloudflare_terrascript_resource_unsupported():
    spec = create_external_resource_spec("doesntexist")

    with pytest.raises(UnsupportedCloudflareResourceError):
        create_cloudflare_terrascript_resource(spec)
