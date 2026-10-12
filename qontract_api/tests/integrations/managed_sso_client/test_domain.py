"""Unit tests for managed_sso_client domain models."""

from qontract_utils.keycloak_api import ManagedKeycloakClient

from qontract_api.integrations.managed_sso_client.domain import (
    AccessType,
    KeycloakInstanceRef,
    ManagedSsoClientDesiredState,
    ManagedSsoClientManagementSecret,
    OidcDesiredState,
)
from qontract_api.models import Secret


def _desired(**oidc_overrides: object) -> ManagedSsoClientDesiredState:
    return ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(
            redirect_uris=["https://example.com/callback"], **oidc_overrides
        ),
    )


def _keycloak_instance() -> KeycloakInstanceRef:
    return KeycloakInstanceRef(
        url="https://sso.example.com/auth/realms/redhat-external",
        initial_access_token=Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/keycloak/iat",
            field="token",
        ),
    )


def test_client_id_is_taken_as_is() -> None:
    """The server never derives client_id from an app/name pair.

    It's app-interface agnostic and takes whatever the caller sends
    verbatim. Any "<app.name>-<name>"-style naming policy is the
    client-side integration's job (compile_desired_state).
    """
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
    )
    assert desired.client_id == "my-app-ci-bot"


def test_enabled_defaults_to_true() -> None:
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(redirect_uris=["https://example.com/callback"]),
    )
    assert desired.enabled is True


def test_to_managed_keycloak_client_carries_enabled() -> None:
    oidc = OidcDesiredState(redirect_uris=["https://example.com/callback"])
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=False)
    assert raw.enabled is False


def test_keycloak_instance_url_is_taken_as_is() -> None:
    """The full realm URL is taken verbatim - nothing derives or appends a path."""
    instance = KeycloakInstanceRef(
        url="https://sso.example.com/auth/realms/redhat-external",
        initial_access_token=Secret(
            secret_manager_url="https://vault.example.com", path="x", field="token"
        ),
    )
    assert instance.url == "https://sso.example.com/auth/realms/redhat-external"


def test_to_managed_keycloak_client_derives_access_type_booleans() -> None:
    oidc = OidcDesiredState(
        access_type=AccessType.PUBLIC,
        redirect_uris=["https://example.com/callback"],
    )
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=True)
    assert raw.public_client is True
    assert raw.bearer_only is False


def test_to_managed_keycloak_client_bearer_only() -> None:
    oidc = OidcDesiredState(
        access_type=AccessType.BEARER_ONLY,
        redirect_uris=[],
    )
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=True)
    assert raw.public_client is False
    assert raw.bearer_only is True


def test_unset_access_type_defaults_to_confidential() -> None:
    """Keycloak's create-time default for an omitted access type is public.

    Not confidential (verified against a live instance) - always resolve
    explicitly instead of relying on it.
    """
    oidc = OidcDesiredState(
        access_type=None,
        redirect_uris=["https://example.com/callback"],
    )
    assert oidc.access_type == AccessType.CONFIDENTIAL


def test_omitted_access_type_defaults_to_confidential() -> None:
    """The realistic case: the key is absent entirely, not sent as null.

    A "before" validator does not run against a field's own default value
    unless validate_default=True is set - must resolve the same way whether
    the caller sends `"access_type": null` or omits the key altogether.
    """
    oidc = OidcDesiredState(redirect_uris=["https://example.com/callback"])
    assert oidc.access_type == AccessType.CONFIDENTIAL


def test_to_managed_keycloak_client_unset_access_type_resolves_to_confidential() -> (
    None
):
    oidc = OidcDesiredState(
        access_type=None,
        redirect_uris=["https://example.com/callback"],
    )
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=True)
    assert raw.public_client is False
    assert raw.bearer_only is False


def test_unset_direct_access_grants_enabled_defaults_to_false() -> None:
    """Keycloak's create-time default for an omitted value is True.

    Enabling the legacy Resource Owner Password Credentials grant by
    default is insecure for most clients - always resolve explicitly
    instead of relying on it (verified against a live instance).
    """
    oidc = OidcDesiredState(
        direct_access_grants_enabled=None,
        redirect_uris=["https://example.com/callback"],
    )
    assert oidc.direct_access_grants_enabled is False


def test_omitted_direct_access_grants_enabled_defaults_to_false() -> None:
    """The realistic case: the key is absent entirely, not sent as null.

    A "before" validator does not run against a field's own default value
    unless validate_default=True is set - must resolve the same way whether
    the caller sends `"direct_access_grants_enabled": null` or omits the
    key altogether.
    """
    oidc = OidcDesiredState(redirect_uris=["https://example.com/callback"])
    assert oidc.direct_access_grants_enabled is False


def test_to_managed_keycloak_client_unset_direct_access_grants_enabled_resolves_to_false() -> (
    None
):
    oidc = OidcDesiredState(
        direct_access_grants_enabled=None,
        redirect_uris=["https://example.com/callback"],
    )
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=True)
    assert raw.direct_access_grants_enabled is False


def test_to_managed_keycloak_client_carries_client_id_and_fields() -> None:
    oidc = OidcDesiredState(
        redirect_uris=["https://example.com/callback"],
        web_origins=["https://example.com"],
        default_client_scopes=["web-origins"],
    )
    raw = oidc.to_managed_keycloak_client(client_id="my-app-ci-bot", enabled=True)
    assert raw.client_id == "my-app-ci-bot"
    assert raw.redirect_uris == ["https://example.com/callback"]
    assert raw.web_origins == ["https://example.com"]
    assert raw.default_client_scopes == ["web-origins"]


def test_matches_ignores_server_owned_fields() -> None:
    current = ManagedKeycloakClient(
        id="server-id",
        secret="s3cr3t",
        registration_access_token="reg-token",
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
    )
    assert _desired().matches(current) is True


def test_matches_ignores_keycloak_managed_attributes() -> None:
    """extra_attributes never registers as drift.

    A live client's attributes map always carries Keycloak-managed entries
    (e.g. client.secret.creation.time) that this schema never declares a
    desired value for - comparing them would cause permanent, spurious drift.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
        extra_attributes={"client.secret.creation.time": "1789043462"},
    )
    assert _desired().matches(current) is True


def test_matches_detects_real_drift() -> None:
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot", redirect_uris=["https://different.example.com"]
    )
    assert _desired().matches(current) is False


def test_matches_ignores_unset_list_fields_even_when_current_has_values() -> None:
    """Unset (None) list fields are unmanaged, not implicitly empty.

    Keycloak's PUT merges by field, so an unset field here is never sent and
    never should be diffed - otherwise reconcile would report permanent
    drift for a value it never actually manages or changes.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
        web_origins=["https://console.example.com"],
        default_client_scopes=["profile"],
        optional_client_scopes=["offline_access"],
    )
    assert _desired().matches(current) is True


def test_matches_ignores_unset_boolean_fields_even_when_current_has_values() -> None:
    """Same unmanaged-when-unset semantic applies to the OIDC booleans.

    Except direct_access_grants_enabled, which - like access_type - always
    resolves to an explicit default instead of staying unmanaged; see
    test_matches_detects_drift_when_direct_access_grants_enabled_defaults_to_false.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
        service_accounts_enabled=True,
        consent_required=True,
        full_scope_allowed=True,
    )
    assert _desired().matches(current) is True


def test_matches_detects_drift_when_direct_access_grants_enabled_defaults_to_false() -> (
    None
):
    """Unset direct_access_grants_enabled resolves to False and is diffed.

    Not left unmanaged like the other OIDC booleans - Keycloak's own
    create-time default (True) is insecure, so this field always has an
    explicit desired value (see the class-level validator).
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=True,
    )
    assert _desired().matches(current) is False


def test_matches_detects_drift_in_explicitly_set_empty_list() -> None:
    """An explicit [] is a real desired value, not "unset" - still diffed."""
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        web_origins=["https://console.example.com"],
    )
    desired = _desired(web_origins=[])
    assert desired.matches(current) is False


def test_management_secret_with_registration_access_token_returns_new_instance() -> (
    None
):
    management = ManagedSsoClientManagementSecret(
        client_id="my-app-ci-bot",
        client_secret="s3cr3t",
        registration_access_token="old-token",
        issuer="https://sso.example.com/auth/realms/redhat-external",
        tenant_secret_path="app-sre/managed-sso-client/output/my-app-ci-bot",
    )
    updated = management.with_registration_access_token("new-token")
    assert updated.registration_access_token == "new-token"
    assert updated.client_id == management.client_id
    assert updated.client_secret == management.client_secret
    # original is untouched (frozen model)
    assert management.registration_access_token == "old-token"


def test_management_secret_with_tenant_secret_path_returns_new_instance() -> None:
    management = ManagedSsoClientManagementSecret(
        client_id="my-app-ci-bot",
        client_secret="s3cr3t",
        registration_access_token="reg-token",
        issuer="https://sso.example.com/auth/realms/redhat-external",
        tenant_secret_path="app-sre/managed-sso-client/output/my-app-ci-bot",
    )
    updated = management.with_tenant_secret_path("app-interface/app-sre/glitchtip/dev")
    assert updated.tenant_secret_path == "app-interface/app-sre/glitchtip/dev"
    assert updated.client_id == management.client_id
    assert updated.client_secret == management.client_secret
    # original is untouched (frozen model)
    assert (
        management.tenant_secret_path
        == "app-sre/managed-sso-client/output/my-app-ci-bot"
    )
