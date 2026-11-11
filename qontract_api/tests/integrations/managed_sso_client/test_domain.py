"""Unit tests for managed_sso_client domain models."""

import pytest
from qontract_utils.keycloak_api import (
    ManagedKeycloakClient,
    ManagedKeycloakProtocolMapper,
)

from qontract_api.integrations.managed_sso_client.domain import (
    AccessType,
    KeycloakInstanceRef,
    ManagedSsoClientDesiredState,
    ManagedSsoClientManagementSecret,
    OidcDesiredState,
    ProtocolMapperDesiredState,
    _declared_mappers_match,
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


def test_matches_ignores_list_order_only_differences() -> None:
    """Keycloak returns list fields from a Set - order is not stable.

    An order-only difference must not register as drift, or every reconcile
    would issue a PUT that flips the order back and forth forever.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=[
            "https://b.example.com/callback",
            "https://a.example.com/callback",
        ],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
    )
    desired = ManagedSsoClientDesiredState(
        client_id="my-app-ci-bot",
        keycloak_instance=_keycloak_instance(),
        oidc=OidcDesiredState(
            redirect_uris=[
                "https://a.example.com/callback",
                "https://b.example.com/callback",
            ]
        ),
    )
    assert desired.matches(current) is True


def test_matches_ignores_duplicate_entries_in_desired_list() -> None:
    """Keycloak collapses list fields to a Set - duplicates in desired are not drift.

    sorted() equality (unlike set() equality) would still see a duplicate
    desired entry as different from Keycloak's deduped value, causing a
    spurious PUT every reconcile.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        enabled=True,
        public_client=False,
        bearer_only=False,
        direct_access_grants_enabled=False,
        optional_client_scopes=["groups"],
    )
    desired = _desired(optional_client_scopes=["groups", "groups"])
    assert desired.matches(current) is True


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


@pytest.mark.parametrize(
    ("desired_uris", "current_uris", "matches"),
    [
        ([], None, True),
        ([], [], True),
        ([], ["+"], False),
        (["+"], None, False),
        (["+"], [], False),
        (["+"], ["+"], True),
        (None, None, True),
        (None, [], True),
        (None, ["+"], True),
    ],
)
def test_matches_post_logout_redirect_uris(
    desired_uris: list[str] | None,
    current_uris: list[str] | None,
    matches: bool,
) -> None:
    desired = _desired(post_logout_redirect_uris=desired_uris)
    current = desired.to_managed_keycloak_client().model_copy(
        update={"post_logout_redirect_uris": current_uris}
    )

    assert desired.matches(current) is matches
    assert desired.immutable_field_drift(current) == []


def test_matches_declared_protocol_mapper_and_attributes() -> None:
    mapper = ManagedKeycloakProtocolMapper(
        name="service-audience",
        protocol_mapper="oidc-audience-mapper",
        config={
            "included.custom.audience": "my-api",
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    )
    desired = _desired(
        protocol_mappers=[
            ProtocolMapperDesiredState.model_validate(mapper.model_dump())
        ],
        attributes={"pkce.code.challenge.method": "S256"},
    )
    base = desired.to_managed_keycloak_client()
    live = base.model_copy(
        update={
            "protocol_mappers": [
                mapper.model_copy(
                    update={
                        "config": {**mapper.config, "userinfo.token.claim": "false"}
                    }
                )
            ],
            "extra_attributes": {
                "pkce.code.challenge.method": "S256",
                "client.secret.creation.time": "123",
            },
        }
    )

    assert desired.matches(live) is True
    assert (
        desired.matches(
            live.model_copy(
                update={"extra_attributes": {"client.secret.creation.time": "123"}}
            )
        )
        is False
    )
    assert desired.matches(live.model_copy(update={"protocol_mappers": []})) is False
    assert desired.matches(
        live.model_copy(update={"protocol_mappers": []}), include_protocol_mappers=False
    )
    assert not desired.matches(
        live.model_copy(update={"protocol_mappers": [], "extra_attributes": {}}),
        include_protocol_mappers=False,
    )
    changed_audience = mapper.model_copy(
        update={
            "config": {
                **mapper.config,
                "included.custom.audience": "different-api",
            }
        }
    )
    assert (
        desired.matches(
            live.model_copy(update={"protocol_mappers": [changed_audience]})
        )
        is False
    )


@pytest.mark.parametrize(
    ("config", "live_config", "matches"),
    [
        (
            {"id.token.claim": "false"},
            {"id.token.claim": "false", "userinfo.token.claim": "false"},
            True,
        ),
        (
            {"id.token.claim": "false"},
            {"id.token.claim": "false", "userinfo.token.claim": "true"},
            True,
        ),
        (
            {"access.token.claim": "true"},
            {"access.token.claim": "true", "server-added": "value"},
            True,
        ),
        ({}, {"included.custom.audience": "retained-audience"}, True),
        (None, {"included.custom.audience": "retained-audience"}, True),
        ({}, {}, True),
        (
            {"included.custom.audience": "new-api"},
            {"included.custom.audience": "old-api"},
            False,
        ),
        ({"access.token.claim": "true"}, {}, False),
        (
            {"access.token.claim": "false"},
            {"access.token.claim": "true"},
            False,
        ),
        (
            {"id.token.claim": "false", "userinfo.token.claim": "false"},
            {"id.token.claim": "false", "userinfo.token.claim": "true"},
            False,
        ),
    ],
)
def test_only_declared_mapper_config_keys_are_checked_for_drift(
    config: dict[str, str] | None,
    live_config: dict[str, str],
    matches: bool,
) -> None:
    declaration = ProtocolMapperDesiredState.model_validate({
        "name": "audience",
        "protocol_mapper": "oidc-audience-mapper",
        **({"config": config} if config is not None else {}),
    })
    mapper = declaration.to_managed_keycloak_mapper()
    desired = _desired(protocol_mappers=[declaration])
    payload = desired.to_managed_keycloak_client()
    assert payload.protocol_mappers is not None
    assert payload.protocol_mappers[0].config == (config if config is not None else {})
    assert mapper.config == (config if config is not None else {})
    current = payload.model_copy(
        update={"protocol_mappers": [mapper.model_copy(update={"config": live_config})]}
    )

    assert desired.matches(current) is matches
    assert desired.immutable_field_drift(current) == (
        [] if matches else ["protocol_mappers"]
    )
    assert _declared_mappers_match([declaration], current.protocol_mappers) is matches


def test_unset_mappers_and_attributes_leave_live_values_unmanaged() -> None:
    live = (
        _desired()
        .to_managed_keycloak_client()
        .model_copy(
            update={
                "protocol_mappers": [
                    ManagedKeycloakProtocolMapper(
                        name="manual",
                        protocol_mapper="oidc-audience-mapper",
                        config={"included.custom.audience": "external"},
                    )
                ],
                "extra_attributes": {"manual.attribute": "value"},
            }
        )
    )
    assert _desired().matches(live) is True
    assert _desired().immutable_field_drift(live) == []


def test_rejects_duplicate_mapper_names_and_attribute_with_dedicated_field() -> None:
    mapper = ManagedKeycloakProtocolMapper(
        name="audience",
        protocol_mapper="oidc-audience-mapper",
        config={"included.custom.audience": "my-api"},
    )
    with pytest.raises(ValueError, match="protocol mapper names must be unique"):
        _desired(
            protocol_mappers=[
                ProtocolMapperDesiredState.model_validate(mapper.model_dump())
            ]
            * 2
        )
    with pytest.raises(ValueError, match="use post_logout_redirect_uris"):
        _desired(attributes={"post.logout.redirect.uris": "https://example.com"})


@pytest.mark.parametrize("value", ["", " ", "\t", "\n", " \t\n", "\u00a0"])
def test_rejects_blank_attribute_values(value: str) -> None:
    with pytest.raises(
        ValueError, match="attribute values must not be empty or whitespace-only"
    ):
        _desired(attributes={"valid.attribute": "value", "blank.attribute": value})


@pytest.mark.parametrize(
    "attributes",
    [None, {}, {"custom.attribute": " value "}, {"custom.attribute": "false"}],
)
def test_preserves_valid_attributes(attributes: dict[str, str] | None) -> None:
    oidc = OidcDesiredState(redirect_uris=[], attributes=attributes)

    assert oidc.attributes == attributes


def test_immutable_field_drift_empty_for_matching_scopes() -> None:
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        default_client_scopes=["profile", "email"],
        optional_client_scopes=["groups"],
    )
    desired = _desired(
        default_client_scopes=["profile", "email"],
        optional_client_scopes=["groups"],
    )
    assert desired.immutable_field_drift(current) == []


def test_immutable_field_drift_empty_for_order_only_differences() -> None:
    """Order-only scope differences must not be reported as immutable drift."""
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        default_client_scopes=["email", "profile"],
    )
    desired = _desired(default_client_scopes=["profile", "email"])
    assert desired.immutable_field_drift(current) == []


def test_immutable_field_drift_empty_for_duplicate_desired_entries() -> None:
    """A duplicate desired scope entry must not permanently block recreation.

    sorted() equality (unlike set() equality) would still report this as
    immutable drift even after a correct delete+recreate with the desired
    scope, since Keycloak's recreated client never has the duplicate.
    """
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        optional_client_scopes=["groups"],
    )
    desired = _desired(optional_client_scopes=["groups", "groups"])
    assert desired.immutable_field_drift(current) == []


def test_immutable_field_drift_detects_optional_client_scopes_change() -> None:
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        optional_client_scopes=["offline_access"],
    )
    desired = _desired(optional_client_scopes=["groups"])
    assert desired.immutable_field_drift(current) == ["optional_client_scopes"]


def test_immutable_field_drift_detects_default_client_scopes_change() -> None:
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        default_client_scopes=["profile"],
    )
    desired = _desired(default_client_scopes=["email"])
    assert desired.immutable_field_drift(current) == ["default_client_scopes"]


def test_immutable_field_drift_detects_both_fields_changed() -> None:
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        default_client_scopes=["profile"],
        optional_client_scopes=["offline_access"],
    )
    desired = _desired(
        default_client_scopes=["email"],
        optional_client_scopes=["groups"],
    )
    assert desired.immutable_field_drift(current) == [
        "default_client_scopes",
        "optional_client_scopes",
    ]


def test_immutable_field_drift_ignores_unmanaged_scope_fields() -> None:
    """A scope field left unset (None) is unmanaged, not implicitly empty."""
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        default_client_scopes=["profile"],
        optional_client_scopes=["offline_access"],
    )
    assert _desired().immutable_field_drift(current) == []


def test_immutable_field_drift_ignores_mutable_field_changes() -> None:
    """A changed mutable field (e.g. web_origins) is not reported as immutable drift."""
    current = ManagedKeycloakClient(
        client_id="my-app-ci-bot",
        redirect_uris=["https://example.com/callback"],
        web_origins=["https://old-origin.example.com"],
    )
    desired = _desired(web_origins=["https://new-origin.example.com"])
    assert desired.immutable_field_drift(current) == []


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


@pytest.mark.parametrize("missing", ["name", "protocol_mapper"])
def test_mapper_requires_name_and_provider(missing: str) -> None:
    declaration = {
        "name": "audience",
        "protocol_mapper": "oidc-audience-mapper",
        "config": {"included.custom.audience": "old-api"},
    }
    del declaration[missing]
    with pytest.raises(ValueError, match="Field required"):
        ProtocolMapperDesiredState.model_validate(declaration)


@pytest.mark.parametrize("deleted", [False, True])
def test_mapper_rejects_removed_deletion_field(deleted: bool) -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ProtocolMapperDesiredState.model_validate({
            "name": "audience",
            "deleted": deleted,
            "protocol_mapper": "oidc-audience-mapper",
            "config": {"included.custom.audience": "old-api"},
        })


def test_mapper_rejects_empty_config_values() -> None:
    with pytest.raises(
        ValueError, match="mapper config values must not be empty strings"
    ):
        ProtocolMapperDesiredState(
            name="audience",
            protocol_mapper="oidc-audience-mapper",
            config={"included.custom.audience": "", "access.token.claim": "true"},
        )


@pytest.mark.parametrize("value", [" ", "\t\n", "\u00a0", " api ", "false"])
def test_mapper_preserves_nonempty_config_values(value: str) -> None:
    mapper = ProtocolMapperDesiredState(
        name="audience",
        protocol_mapper="oidc-audience-mapper",
        config={"included.custom.audience": value},
    )
    assert mapper.to_managed_keycloak_mapper().to_raw().config == {
        "included.custom.audience": value
    }


@pytest.mark.parametrize("mappers", [None, []])
def test_empty_declarations_preserve_live_mappers(
    mappers: list[ProtocolMapperDesiredState] | None,
) -> None:
    desired = _desired(protocol_mappers=mappers)
    current = desired.to_managed_keycloak_client().with_protocol_mappers([
        ManagedKeycloakProtocolMapper(
            name="external", protocol_mapper="oidc-full-name-mapper", config={}
        )
    ])
    assert desired.matches(current)
    assert desired.immutable_field_drift(current) == []
    assert _declared_mappers_match(mappers, current.protocol_mappers)
    assert desired.to_managed_keycloak_client().protocol_mappers is None


def test_matching_declaration_ignores_external_mapper() -> None:
    declaration = ProtocolMapperDesiredState(
        name="audience", protocol_mapper="oidc-audience-mapper", config={}
    )
    desired = _desired(protocol_mappers=[declaration])
    current = desired.to_managed_keycloak_client().with_protocol_mappers([
        declaration.to_managed_keycloak_mapper(),
        ManagedKeycloakProtocolMapper(
            name="external", protocol_mapper="oidc-full-name-mapper", config={}
        ),
    ])
    assert desired.matches(current)
    assert desired.immutable_field_drift(current) == []
