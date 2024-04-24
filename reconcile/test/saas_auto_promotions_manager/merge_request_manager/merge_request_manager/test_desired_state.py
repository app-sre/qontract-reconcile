from collections.abc import Callable

from reconcile.saas_auto_promotions_manager.merge_request_manager.desired_state import (
    DesiredState,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

from .data_keys import (
    CHANNEL,
)


def test_desired_state_empty() -> None:
    desired_state = DesiredState(subscribers=[])
    assert desired_state.promotions == []


def test_desired_state_single_subscriber(
    subscriber_builder: Callable[..., Subscriber],
) -> None:
    subscriber = subscriber_builder({})
    desired_state = DesiredState(subscribers=[subscriber])
    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber])
    }


def test_desired_state_multiple_subscribers_same_channel_combo(
    subscriber_builder: Callable[..., Subscriber],
) -> None:
    subscriber_a = subscriber_builder({CHANNEL: ["channel-a", "channel-b"]})
    subscriber_a.desired_ref = "ref-a"
    subscriber_b = subscriber_builder({CHANNEL: ["channel-a", "channel-b"]})
    subscriber_b.desired_ref = "ref-b"
    desired_state = DesiredState(subscribers=[subscriber_a, subscriber_b])
    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber_a, subscriber_b]),
    }


def test_desired_state_multiple_subscribers_different_channel_combo(
    subscriber_builder: Callable[..., Subscriber],
) -> None:
    subscriber_a = subscriber_builder({CHANNEL: ["channel-a", "channel-b"]})
    subscriber_a.desired_ref = "ref-a"
    subscriber_b = subscriber_builder({CHANNEL: ["channel-a", "channel-b"]})
    subscriber_b.desired_ref = "ref-b"
    subscriber_c = subscriber_builder({CHANNEL: ["channel-b", "channel-c"]})
    subscriber_c.desired_ref = "ref-c"
    desired_state = DesiredState(subscribers=[subscriber_a, subscriber_b, subscriber_c])
    sorted_promotions = sorted(desired_state.promotions)
    assert len(desired_state.promotions) == 2
    assert sorted_promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber_a, subscriber_b]),
    }
    assert sorted_promotions[1].content_hashes == {
        Subscriber.combined_content_hash([subscriber_c]),
    }
