from cloudevents.pydantic.v2.event import CloudEvent
from qontract_utils.events import Event


def test_event_is_cloud_event_subclass() -> None:
    assert issubclass(Event, CloudEvent)


def test_event_creation() -> None:
    event = Event(
        source="test-source",
        type="test.event.created",
        data={"key": "value"},
    )
    assert event["source"] == "test-source"
    assert event["type"] == "test.event.created"
    assert event.data == {"key": "value"}


def test_event_data_content_type() -> None:
    event = Event(
        source="test-source",
        type="test.event",
        data={"foo": "bar"},
        datacontenttype="application/json",
    )
    assert event["datacontenttype"] == "application/json"


def test_event_with_complex_data() -> None:
    data = {
        "users": [{"name": "Alice"}, {"name": "Bob"}],
        "count": 2,
        "nested": {"deep": True},
    }
    event = Event(
        source="test-source",
        type="test.event",
        data=data,
    )
    assert event.data == data


def test_event_with_none_data() -> None:
    event = Event(
        source="test-source",
        type="test.event",
    )
    assert event.data is None


def test_event_json_roundtrip() -> None:
    event = Event(
        source="test-source",
        type="test.event",
        data={"key": "value"},
    )
    json_str = event.model_dump_json()
    restored = Event.model_validate_json(json_str)
    assert restored["source"] == event["source"]
    assert restored["type"] == event["type"]
    assert restored.data == event.data
