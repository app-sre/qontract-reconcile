from pydantic import BaseModel
from qontract_utils.events import Event


def test_event_is_pydantic_model() -> None:
    assert issubclass(Event, BaseModel)


def test_event_defaults() -> None:
    event = Event(source="s", type="t")
    assert event.specversion == "1.0"
    assert event.id
    assert event.time is not None
    assert event.data is None
    assert event.datacontenttype is None


def test_event_creation() -> None:
    event = Event(
        source="test-source",
        type="test.event.created",
        data={"key": "value"},
    )
    assert event.source == "test-source"
    assert event.type == "test.event.created"
    assert event.data == {"key": "value"}


def test_event_data_content_type() -> None:
    event = Event(
        source="test-source",
        type="test.event",
        data={"foo": "bar"},
        datacontenttype="application/json",
    )
    assert event.datacontenttype == "application/json"


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
    assert restored.source == event.source
    assert restored.type == event.type
    assert restored.data == event.data
