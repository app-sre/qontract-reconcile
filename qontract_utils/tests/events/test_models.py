from datetime import UTC, datetime

from qontract_utils.events.models import Event


def test_event_creation() -> None:
    event = Event(
        event_type="slack-usergroups.update_users",
        source="qontract-api",
        payload={"workspace": "test", "usergroup": "team-a"},
    )
    assert event.version == 1
    assert event.event_type == "slack-usergroups.update_users"
    assert event.source == "qontract-api"
    assert event.payload == {"workspace": "test", "usergroup": "team-a"}
    assert event.timestamp.tzinfo is not None


def test_event_default_timestamp() -> None:
    before = datetime.now(tz=UTC)
    event = Event(event_type="test.event", source="test")
    after = datetime.now(tz=UTC)
    assert before <= event.timestamp <= after


def test_event_default_payload() -> None:
    event = Event(event_type="test.event", source="test")
    assert event.payload == {}


def test_event_json_round_trip() -> None:
    event = Event(
        event_type="slack-usergroups.update_users",
        source="qontract-api",
        payload={"workspace": "test", "users": ["alice", "bob"]},
    )
    json_str = event.model_dump_json()
    restored = Event.model_validate_json(json_str)
    assert restored == event


def test_event_frozen() -> None:
    event = Event(event_type="test.event", source="test")
    try:
        event.event_type = "other"  # type: ignore[misc]
    except Exception:  # noqa: BLE001, S110
        pass
    else:
        msg = "Event should be frozen"
        raise AssertionError(msg)


def test_event_custom_version() -> None:
    event = Event(version=2, event_type="test.event", source="test")
    assert event.version == 2
