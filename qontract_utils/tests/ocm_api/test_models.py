"""Tests for qontract_utils.ocm_api.models."""

from qontract_utils.ocm_api.models import (
    OcmCluster,
    OcmIdentityProvider,
    OcmIdentityProviderOidc,
    OcmIdentityProviderOidcOpenId,
    OcmIdentityProviderOidcOpenIdClaims,
    OcmOrganizationLabel,
    OcmSubscription,
    OcmSubscriptionLabel,
)


def test_ocm_subscription_label_fields() -> None:
    label = OcmSubscriptionLabel(key="k", value="v", subscription_id="sub-1")
    assert label.key == "k"
    assert label.value == "v"
    assert label.subscription_id == "sub-1"


def test_ocm_organization_label_fields() -> None:
    label = OcmOrganizationLabel(key="k", value="v", organization_id="org-1")
    assert label.key == "k"
    assert label.value == "v"
    assert label.organization_id == "org-1"


def test_ocm_subscription_roundtrip() -> None:
    subscription = OcmSubscription(
        id="sub-1", organization_id="org-1", status="Active", managed=True
    )
    assert subscription.id == "sub-1"
    assert subscription.organization_id == "org-1"
    assert subscription.status == "Active"
    assert subscription.managed is True


def test_ocm_cluster_console_url_optional() -> None:
    cluster = OcmCluster(
        id="cluster-1",
        name="my-cluster",
        subscription_id="sub-1",
        console_url=None,
        external_auth_enabled=False,
    )
    assert cluster.console_url is None


def test_ocm_cluster_with_console_url() -> None:
    cluster = OcmCluster(
        id="cluster-1",
        name="my-cluster",
        subscription_id="sub-1",
        console_url="https://console.example.com",
        external_auth_enabled=True,
    )
    assert cluster.console_url == "https://console.example.com"
    assert cluster.external_auth_enabled is True


def _oidc_idp(
    *, client_secret: str | None, groups: list[str] | None = None
) -> OcmIdentityProviderOidc:
    return OcmIdentityProviderOidc(
        name="redhat-sso",
        id="idp-1",
        open_id=OcmIdentityProviderOidcOpenId(
            client_id="client-1",
            client_secret=client_secret,
            issuer="https://issuer.example.com",
            claims=OcmIdentityProviderOidcOpenIdClaims(groups=groups or []),
        ),
    )


def test_ocm_identity_provider_oidc_equality_ignores_client_secret() -> None:
    """Equality must ignore client_secret.

    OCM never returns the client secret on read, so a freshly-read 'current' instance
    (secret=None) must still compare equal to a 'desired' instance built with the real
    secret - otherwise every reconcile would see a spurious diff.
    """
    current = _oidc_idp(client_secret=None)
    desired = _oidc_idp(client_secret="the-real-secret")

    assert current == desired


def test_ocm_identity_provider_oidc_equality_ignores_id() -> None:
    """Equality must ignore id.

    id is assigned by OCM and only known on the 'current' side - the diff must still
    recognize a matching desired object with no id set as equal.
    """
    current = _oidc_idp(client_secret=None)
    desired = current.model_copy(update={"id": None})

    assert current == desired


def test_ocm_identity_provider_oidc_inequality_on_issuer() -> None:
    current = _oidc_idp(client_secret=None)
    desired = OcmIdentityProviderOidc(
        name="redhat-sso",
        open_id=OcmIdentityProviderOidcOpenId(
            client_id="client-1",
            issuer="https://different-issuer.example.com",
        ),
    )

    assert current != desired


def test_ocm_identity_provider_oidc_inequality_on_claims() -> None:
    current = _oidc_idp(client_secret=None, groups=[])
    desired = _oidc_idp(client_secret=None, groups=["filtered_groups"])

    assert current != desired


def test_ocm_identity_provider_oidc_not_equal_to_other_type() -> None:
    idp = _oidc_idp(client_secret=None)
    assert idp != OcmIdentityProvider(type="GithubIdentityProvider", name="x")


def test_ocm_identity_provider_generic_classification() -> None:
    idp = OcmIdentityProvider(type="GithubIdentityProvider", name="github", id="idp-2")
    assert idp.type == "GithubIdentityProvider"
    assert idp.name == "github"
