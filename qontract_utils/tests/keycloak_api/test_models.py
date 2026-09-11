"""Tests for qontract_utils.keycloak_api.models."""

from qontract_utils.keycloak_api._raw_client import RawClientRepresentation
from qontract_utils.keycloak_api.models import KeycloakSsoClient, ManagedKeycloakClient


def test_keycloak_sso_client_fields() -> None:
    sso_client = KeycloakSsoClient(
        client_id="my-client",
        client_secret="s3cr3t",
        redirect_uris=["https://example.com/callback"],
        registration_access_token="reg-token",
        attributes={"what": "ever"},
    )
    assert sso_client.client_id == "my-client"
    assert sso_client.client_secret == "s3cr3t"
    assert sso_client.redirect_uris == ["https://example.com/callback"]
    assert sso_client.registration_access_token == "reg-token"
    assert sso_client.attributes == {"what": "ever"}


def _minimal(**overrides: object) -> ManagedKeycloakClient:
    defaults: dict[str, object] = {
        "client_id": "my-app-my-client",
        "redirect_uris": ["https://example.com/callback"],
    }
    return ManagedKeycloakClient.model_validate({**defaults, **overrides})


def test_to_raw_uses_camel_case_aliases_for_top_level_fields() -> None:
    raw = _minimal(
        enabled=True,
        standard_flow_enabled=None,
        default_client_scopes=["web-origins"],
    ).to_raw()
    body = raw.model_dump(mode="json")

    assert body["clientId"] == "my-app-my-client"
    assert body["redirectUris"] == ["https://example.com/callback"]
    assert body["enabled"] is True
    assert body["defaultClientScopes"] == ["web-origins"]


def test_to_raw_joins_post_logout_redirect_uris_with_double_hash() -> None:
    raw = _minimal(
        post_logout_redirect_uris=["https://a.example.com", "https://b.example.com"]
    ).to_raw()

    assert raw.attributes is not None
    assert raw.attributes["post.logout.redirect.uris"] == (
        "https://a.example.com##https://b.example.com"
    )


def test_to_raw_carries_extra_attributes() -> None:
    raw = _minimal(extra_attributes={"group-filter-regex": "^my-group-.*$"}).to_raw()

    assert raw.attributes == {"group-filter-regex": "^my-group-.*$"}


def test_to_raw_omits_attributes_key_when_nothing_to_carry() -> None:
    raw = _minimal().to_raw()
    assert raw.attributes is None


def test_to_raw_omits_unset_optional_list_fields_from_wire_payload() -> None:
    """Unset (None) is "don't manage this field", not "send it as empty".

    Keycloak's PUT merges by field: an omitted key leaves the existing value
    untouched, while an explicit [] would actively clear it. Only exercising
    exclude_none=True (as register_client/update_client actually do) proves
    the field is genuinely omitted, not just None in the Python object.
    """
    raw = _minimal().to_raw()
    body = raw.model_dump(mode="json", exclude_none=True)

    assert "webOrigins" not in body
    assert "defaultClientScopes" not in body
    assert "optionalClientScopes" not in body


def test_to_raw_sends_explicit_empty_list_when_set() -> None:
    """An explicitly empty list is a real desired value, not "unset"."""
    raw = _minimal(web_origins=[]).to_raw()
    body = raw.model_dump(mode="json", exclude_none=True)

    assert body["webOrigins"] == []


def test_from_raw_splits_post_logout_redirect_uris() -> None:
    raw = RawClientRepresentation(
        client_id="c",
        attributes={
            "post.logout.redirect.uris": "https://a.example.com##https://b.example.com"
        },
    )

    parsed = ManagedKeycloakClient.from_raw(raw)

    assert parsed.post_logout_redirect_uris == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_from_raw_preserves_unmodeled_attributes_as_extra() -> None:
    raw = RawClientRepresentation(
        client_id="c", attributes={"some.unmodeled.attribute": "value"}
    )

    parsed = ManagedKeycloakClient.from_raw(raw)

    assert parsed.extra_attributes == {"some.unmodeled.attribute": "value"}


def test_from_raw_handles_missing_attributes() -> None:
    raw = RawClientRepresentation(client_id="c")

    parsed = ManagedKeycloakClient.from_raw(raw)

    assert parsed.extra_attributes == {}
    assert parsed.post_logout_redirect_uris == []


def test_to_raw_from_raw_round_trip() -> None:
    original = _minimal(
        web_origins=["https://example.com"],
        public_client=False,
        bearer_only=False,
        consent_required=True,
        direct_access_grants_enabled=True,
        service_accounts_enabled=False,
        full_scope_allowed=True,
        post_logout_redirect_uris=["https://example.com/logged-out"],
        extra_attributes={"some.custom.attribute": "value"},
    )

    round_tripped = ManagedKeycloakClient.from_raw(original.to_raw())

    assert round_tripped.client_id == original.client_id
    assert round_tripped.redirect_uris == original.redirect_uris
    assert round_tripped.web_origins == original.web_origins
    assert round_tripped.public_client == original.public_client
    assert round_tripped.bearer_only == original.bearer_only
    assert round_tripped.consent_required == original.consent_required
    assert (
        round_tripped.direct_access_grants_enabled
        == original.direct_access_grants_enabled
    )
    assert round_tripped.service_accounts_enabled == original.service_accounts_enabled
    assert round_tripped.full_scope_allowed == original.full_scope_allowed
    assert round_tripped.post_logout_redirect_uris == original.post_logout_redirect_uris
    assert round_tripped.extra_attributes == original.extra_attributes
