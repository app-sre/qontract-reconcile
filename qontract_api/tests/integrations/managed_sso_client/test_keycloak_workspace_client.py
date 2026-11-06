"""Unit tests for managed_sso_client's KeycloakWorkspaceClient (caching + locking)."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.keycloak_api import (
    ManagedKeycloakClient,
    ManagedKeycloakProtocolMapper,
)

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.managed_sso_client.domain import (
    ProtocolMapperDesiredState,
)
from qontract_api.integrations.managed_sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)

INSTANCE_URL = "https://sso.example.com/auth/realms/redhat-external"
CACHE_KEY = f"managed-sso-client:{INSTANCE_URL}:my-app-ci-bot"


@pytest.fixture
def mock_api() -> MagicMock:
    mock = MagicMock()
    mock.url = INSTANCE_URL
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def client(
    mock_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> KeycloakWorkspaceClient:
    return KeycloakWorkspaceClient(
        keycloak_api=mock_api, cache=mock_cache, settings=mock_settings
    )


def _client_repr(client_id: str = "my-app-ci-bot") -> ManagedKeycloakClient:
    return ManagedKeycloakClient(
        client_id=client_id, redirect_uris=["https://example.com/callback"]
    )


# ---------------------------------------------------------------------------
# register_client
# ---------------------------------------------------------------------------


def test_register_client_is_locked_per_instance_and_client_id(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    client.register_client(_client_repr())

    mock_cache.lock.assert_called_once_with(CACHE_KEY)
    mock_api.register_client.assert_called_once()


# ---------------------------------------------------------------------------
# get_client - cache hit
# ---------------------------------------------------------------------------


def test_get_client_cache_hit_skips_api_call(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    cached = _client_repr()
    mock_cache.get_obj.return_value = cached

    result = client.get_client("my-app-ci-bot", "reg-token")

    assert result == cached
    mock_api.get_client.assert_not_called()


def test_get_client_cache_hit_skips_lock(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.lock.assert_not_called()


# ---------------------------------------------------------------------------
# get_client - cache miss
# ---------------------------------------------------------------------------


def test_get_client_cache_miss_calls_api_with_registration_access_token(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = None
    mock_api.get_client.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_api.get_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )


def test_get_client_cache_miss_acquires_lock(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = None
    mock_api.get_client.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.lock.assert_called_once_with(CACHE_KEY)


def test_get_client_cache_miss_stores_result_with_configured_ttl(
    client: KeycloakWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    fetched = _client_repr()
    mock_api.get_client.return_value = fetched

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.set_obj.assert_called_once_with(
        CACHE_KEY, fetched, mock_settings.managed_sso_client.client_cache_ttl
    )


def test_get_client_double_check_inside_lock(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Second get_obj call (inside lock) returns data -> API must not be called."""
    cached = _client_repr()
    mock_cache.get_obj.side_effect = [None, cached]

    result = client.get_client("my-app-ci-bot", "reg-token")

    assert result == cached
    mock_api.get_client.assert_not_called()
    mock_cache.set_obj.assert_not_called()


# ---------------------------------------------------------------------------
# update_client - delegates + invalidates
# ---------------------------------------------------------------------------


def test_update_client_delegates_to_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    data = _client_repr()

    client.update_client("my-app-ci-bot", "reg-token", data)

    mock_api.update_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token", data=data
    )


def test_update_preserves_fresh_mapper_config_and_overrides_declared_keys(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mapper = ManagedKeycloakProtocolMapper(
        name="audience",
        protocol_mapper="oidc-audience-mapper",
        config={
            "included.custom.audience": "old-api",
            "access.token.claim": "true",
            "id.token.claim": "true",
        },
    )
    current = _client_repr().model_copy(update={"protocol_mappers": [mapper]})
    mock_api.get_client.return_value = current
    mock_cache.get_obj.return_value = _client_repr()
    desired_mapper = mapper.model_copy(
        update={
            "config": {"included.custom.audience": "new-api", "id.token.claim": "false"}
        }
    )
    data = _client_repr().model_copy(update={"protocol_mappers": [desired_mapper]})

    client.update_client(
        "my-app-ci-bot",
        "reg-token",
        data,
        mapper_declarations=[
            ProtocolMapperDesiredState.model_validate(desired_mapper.model_dump())
        ],
    )

    mock_api.get_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )
    mock_cache.get_obj.assert_not_called()
    mock_cache.lock.assert_called_once_with(CACHE_KEY)
    sent = mock_api.update_client.call_args.kwargs["data"]
    assert sent.protocol_mappers[0].config == {
        "included.custom.audience": "new-api",
        "access.token.claim": "true",
        "id.token.claim": "false",
    }
    assert desired_mapper.config == {
        "included.custom.audience": "new-api",
        "id.token.claim": "false",
    }
    assert mapper.config == {
        "included.custom.audience": "old-api",
        "access.token.claim": "true",
        "id.token.claim": "true",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "new-mapper"},
        {"protocol": "different-protocol"},
        {"protocol_mapper": "different-type"},
    ],
)
def test_update_does_not_inherit_config_from_other_mappers(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, changes: dict[str, str]
) -> None:
    live_mapper = ManagedKeycloakProtocolMapper(
        name="audience",
        protocol_mapper="oidc-audience-mapper",
        config={"live-only": "value"},
    )
    mock_api.get_client.return_value = _client_repr().model_copy(
        update={"protocol_mappers": [live_mapper]}
    )
    desired_mapper = live_mapper.model_copy(
        update={**changes, "config": {"declared": "value"}}
    )
    data = _client_repr().model_copy(update={"protocol_mappers": [desired_mapper]})

    client.update_client(
        "my-app-ci-bot",
        "reg-token",
        data,
        mapper_declarations=[
            ProtocolMapperDesiredState.model_validate(desired_mapper.model_dump())
        ],
    )

    expected = (
        [desired_mapper]
        if "protocol_mapper" in changes
        else [live_mapper, desired_mapper]
    )
    assert mock_api.update_client.call_args.kwargs["data"].protocol_mappers == expected


@pytest.mark.parametrize("mappers", [None, []])
def test_update_preserves_unmanaged_or_empty_mapper_list_without_fetching(
    client: KeycloakWorkspaceClient,
    mock_api: MagicMock,
    mappers: list[ProtocolMapperDesiredState] | None,
) -> None:
    data = _client_repr()

    client.update_client(
        "my-app-ci-bot", "reg-token", data, mapper_declarations=mappers
    )

    mock_api.get_client.assert_not_called()
    sent = mock_api.update_client.call_args.kwargs["data"]
    assert "protocolMappers" not in sent.to_raw().model_dump(exclude_none=True)


def test_update_does_not_write_if_fetching_mapper_config_fails(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mapper = ManagedKeycloakProtocolMapper(
        name="audience", protocol_mapper="oidc-audience-mapper", config={}
    )
    data = _client_repr().model_copy(update={"protocol_mappers": [mapper]})
    mock_api.get_client.side_effect = RuntimeError("keycloak unreachable")

    with pytest.raises(RuntimeError, match="keycloak unreachable"):
        client.update_client(
            "my-app-ci-bot",
            "reg-token",
            data,
            mapper_declarations=[
                ProtocolMapperDesiredState.model_validate(mapper.model_dump())
            ],
        )

    mock_api.update_client.assert_not_called()
    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_update_client_invalidates_cache(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_update_client_is_locked_per_instance_and_client_id(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    mock_cache.lock.assert_called_once_with(CACHE_KEY)


def test_update_client_invalidates_cache_even_when_api_call_raises(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """A lost response for a PUT must not leave a stale cache entry.

    Otherwise a PUT Keycloak actually applied could leave a stale cached
    value behind until the cache TTL expires.
    """
    mock_api.update_client.side_effect = RuntimeError("timeout")

    with pytest.raises(RuntimeError):
        client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_update_client_cache_delete_failure_does_not_mask_successful_update(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """A cache backend error must not replace a successful update's result."""
    updated = _client_repr()
    mock_api.update_client.return_value = updated
    mock_cache.delete.side_effect = ConnectionError("redis unreachable")

    result = client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    assert result == updated


def test_update_client_cache_delete_failure_does_not_mask_api_exception(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """A cache backend error must not replace the real Keycloak exception."""
    mock_api.update_client.side_effect = RuntimeError("timeout")
    mock_cache.delete.side_effect = ConnectionError("redis unreachable")

    with pytest.raises(RuntimeError, match="timeout"):
        client.update_client("my-app-ci-bot", "reg-token", _client_repr())


# ---------------------------------------------------------------------------
# delete_client - delegates + invalidates
# ---------------------------------------------------------------------------


def test_delete_client_delegates_to_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    client.delete_client("my-app-ci-bot", "reg-token")

    mock_api.delete_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )


def test_delete_client_invalidates_cache(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.delete_client("my-app-ci-bot", "reg-token")

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_delete_client_invalidates_cache_even_when_api_call_raises(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """A stale cache entry must not survive a 404 the caller treats as already-deleted.

    Otherwise a same-client_id client registered later could be diffed
    against the deleted client's cached representation for up to the cache
    TTL - under immutable_field_drift() this could wrongly block a
    legitimate delete+recreate.
    """
    mock_api.delete_client.side_effect = RuntimeError("404 not found")

    with pytest.raises(RuntimeError):
        client.delete_client("my-app-ci-bot", "reg-token")

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_delete_client_cache_delete_failure_does_not_mask_api_exception(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """A cache backend error must not replace the real Keycloak exception."""
    mock_api.delete_client.side_effect = RuntimeError("404 not found")
    mock_cache.delete.side_effect = ConnectionError("redis unreachable")

    with pytest.raises(RuntimeError, match="404 not found"):
        client.delete_client("my-app-ci-bot", "reg-token")


def test_delete_client_cache_delete_failure_does_not_raise_on_success(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    """A cache backend error must not surface when the Keycloak call succeeded."""
    mock_cache.delete.side_effect = ConnectionError("redis unreachable")

    client.delete_client("my-app-ci-bot", "reg-token")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_close_closes_underlying_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    client.close()
    mock_api.close.assert_called_once()


@pytest.mark.parametrize("target_exists", [True, False])
def test_update_merges_creates_updates_and_explicit_deletions(
    client: KeycloakWorkspaceClient,
    mock_api: MagicMock,
    *,
    target_exists: bool,
) -> None:
    external = ManagedKeycloakProtocolMapper(
        name="external", protocol_mapper="oidc-full-name-mapper", config={"keep": "yes"}
    )
    target = ManagedKeycloakProtocolMapper(
        name="obsolete", protocol_mapper="oidc-audience-mapper", config={}
    )
    live_audience = ManagedKeycloakProtocolMapper(
        name="audience",
        protocol_mapper="oidc-audience-mapper",
        config={"included.custom.audience": "old-api", "server-added": "preserved"},
    )
    live = (
        [external, live_audience, target]
        if target_exists
        else [external, live_audience]
    )
    mock_api.get_client.return_value = _client_repr().with_protocol_mappers(live)
    declarations = [
        ProtocolMapperDesiredState(
            name="obsolete",
            deleted=True,
            protocol_mapper="oidc-audience-mapper",
            config={"included.custom.audience": "old-api"},
        ),
        ProtocolMapperDesiredState(
            name="audience",
            protocol_mapper="oidc-audience-mapper",
            config={"included.custom.audience": "new-api"},
        ),
        ProtocolMapperDesiredState(
            name="new", protocol_mapper="oidc-address-mapper", config={}
        ),
    ]

    client.update_client(
        "my-app-ci-bot", "reg-token", _client_repr(), mapper_declarations=declarations
    )

    sent = mock_api.update_client.call_args.kwargs["data"]
    assert sent.protocol_mappers == [
        external,
        live_audience.with_config({
            "included.custom.audience": "new-api",
            "server-added": "preserved",
        }),
        declarations[2].to_managed_keycloak_mapper(),
    ]
    assert all(
        "deleted" not in m for m in sent.to_raw().model_dump()["protocolMappers"]
    )
    assert live_audience.config["included.custom.audience"] == "old-api"


def test_deleting_last_mapper_sends_explicit_empty_list(
    client: KeycloakWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    mock_api.get_client.return_value = _client_repr().with_protocol_mappers([
        ManagedKeycloakProtocolMapper(
            name="audience", protocol_mapper="oidc-audience-mapper", config={}
        )
    ])
    client.update_client(
        "my-app-ci-bot",
        "reg-token",
        _client_repr(),
        mapper_declarations=[
            ProtocolMapperDesiredState(
                name="audience",
                deleted=True,
                protocol_mapper="oidc-audience-mapper",
                config={"included.custom.audience": "old-api"},
            )
        ],
    )
    sent = mock_api.update_client.call_args.kwargs["data"]
    assert sent.to_raw().model_dump(exclude_none=True)["protocolMappers"] == []
