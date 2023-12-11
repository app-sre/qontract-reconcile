from collections.abc import Callable

from httpretty.core import HTTPrettyRequest

from reconcile.test.ocm.fixtures import (
    OcmUrl,
    build_ocm_cluster,
)
from reconcile.utils.ocm.base import (
    OCMOIdentityProvider,
    OCMOIdentityProviderGithub,
    OCMOIdentityProviderOidc,
    OCMOIdentityProviderOidcOpenId,
)
from reconcile.utils.ocm.identity_providers import (
    add_identity_provider,
    delete_identity_provider,
    get_identity_providers,
    update_identity_provider,
)
from reconcile.utils.ocm_base_client import OCMBaseClient

IDP_OIDC = OCMOIdentityProviderOidc(
    href="/api/foobar/1",
    name="oidc-auth",
    open_id=OCMOIdentityProviderOidcOpenId(
        client_id="client-id-cluster-1",
        issuer="https://issuer.com",
    ),
)
IDP_GH = OCMOIdentityProviderGithub(href="/api/foobar/2", id="idp-2", name="gh-auth")
IDP_OTHER = OCMOIdentityProvider(
    href="/api/foobar/3", id="idp-3", name="other-auth", type="other"
)


def test_utils_get_subscription_labels(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    ocm_cluster = build_ocm_cluster("cluster")
    ocm_cluster.identity_providers.href = "/api/foobar"
    register_ocm_url_responses([
        OcmUrl(
            method="GET", uri=ocm_cluster.identity_providers.href
        ).add_list_response([
            IDP_OIDC.dict(by_alias=True),
            IDP_GH.dict(by_alias=True),
            IDP_OTHER.dict(by_alias=True),
        ])
    ])

    assert list(get_identity_providers(ocm_api, ocm_cluster)) == [
        IDP_OIDC,
        IDP_GH,
        IDP_OTHER,
    ]


def test_add_identity_provider(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[HTTPrettyRequest]],
) -> None:
    ocm_cluster = build_ocm_cluster("cluster")
    ocm_cluster.identity_providers.href = "/api/foobar"
    register_ocm_url_responses([
        OcmUrl(method="POST", uri=ocm_cluster.identity_providers.href)
    ])
    add_identity_provider(ocm_api, ocm_cluster, IDP_OIDC)
    ocm_calls = find_all_ocm_http_requests("POST")
    assert len(ocm_calls) == 1


def test_update_identity_provider(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[HTTPrettyRequest]],
) -> None:
    register_ocm_url_responses([OcmUrl(method="PATCH", uri=IDP_OIDC.href)])
    update_identity_provider(ocm_api, IDP_OIDC)
    ocm_calls = find_all_ocm_http_requests("PATCH")
    assert len(ocm_calls) == 1


def test_delete_identity_provider(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str], list[HTTPrettyRequest]],
) -> None:
    register_ocm_url_responses([OcmUrl(method="DELETE", uri=IDP_OTHER.href)])
    delete_identity_provider(ocm_api, IDP_OTHER)
    ocm_calls = find_all_ocm_http_requests("DELETE")
    assert len(ocm_calls) == 1
