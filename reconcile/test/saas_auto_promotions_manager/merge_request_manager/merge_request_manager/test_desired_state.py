from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from unittest.mock import create_autospec

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.desired_state import (
    DesiredState,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.schedule import (
    Schedule,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

from .data_keys import (
    CHANNEL,
    DESIRED_REF,
    SOAK_DAYS,
)


def test_desired_state_empty() -> None:
    desired_state = DesiredState(subscribers=[], open_mrs=[])
    assert desired_state.promotions == []


def test_desired_state_single_subscriber(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber = subscriber_builder({})
    desired_state = DesiredState(subscribers=[subscriber], open_mrs=[])
    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber])
    }


def test_desired_state_multiple_subscribers_same_channel_combo(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber_a = subscriber_builder({
        CHANNEL: {"channel-a": {}, "channel-b": {}},
        DESIRED_REF: "ref-a",
    })
    subscriber_b = subscriber_builder({
        CHANNEL: {"channel-a": {}, "channel-b": {}},
        DESIRED_REF: "ref-b",
    })
    desired_state = DesiredState(subscribers=[subscriber_a, subscriber_b], open_mrs=[])
    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber_a, subscriber_b]),
    }


def test_desired_state_multiple_subscribers_different_channel_combo(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber_a = subscriber_builder({
        CHANNEL: {"channel-a": {}, "channel-b": {}},
        DESIRED_REF: "ref-a",
    })
    subscriber_b = subscriber_builder({
        CHANNEL: {"channel-a": {}, "channel-b": {}},
        DESIRED_REF: "ref-b",
    })
    subscriber_c = subscriber_builder({
        CHANNEL: {"channel-b": {}, "channel-c": {}},
        DESIRED_REF: "ref-c",
    })
    desired_state = DesiredState(
        subscribers=[subscriber_a, subscriber_b, subscriber_c], open_mrs=[]
    )
    sorted_promotions = sorted(desired_state.promotions)
    assert len(desired_state.promotions) == 2
    assert sorted_promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber_a, subscriber_b]),
    }
    assert sorted_promotions[1].content_hashes == {
        Subscriber.combined_content_hash([subscriber_c]),
    }


def test_desired_state_new_schedule(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        SOAK_DAYS: 1,
    })
    expected_after = datetime.now(tz=timezone.utc) + timedelta(days=1)
    expected_before = datetime.now(tz=timezone.utc) + timedelta(days=1, minutes=1)
    desired_state = DesiredState(subscribers=[subscriber], open_mrs=[])
    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].content_hashes == {
        Subscriber.combined_content_hash([subscriber])
    }
    assert not desired_state.promotions[0].schedule.is_now()
    assert desired_state.promotions[0].schedule.after >= expected_after
    assert desired_state.promotions[0].schedule.after < expected_before


def test_desired_state_new_schedule_and_no_soak_days(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber_with_soak_days = subscriber_builder({
        DESIRED_REF: "ref-a",
        SOAK_DAYS: 1,
    })

    subscriber_without_soak_days = subscriber_builder({
        DESIRED_REF: "ref-b",
    })

    expected_after = datetime.now(tz=timezone.utc) + timedelta(days=1)
    expected_before = datetime.now(tz=timezone.utc) + timedelta(days=1, minutes=1)

    desired_state = DesiredState(
        subscribers=[subscriber_with_soak_days, subscriber_without_soak_days],
        open_mrs=[],
    )
    promotions = sorted(desired_state.promotions)

    assert len(desired_state.promotions) == 2
    assert not promotions[0].schedule.is_now()
    assert promotions[0].schedule.after >= expected_after
    assert promotions[0].schedule.after < expected_before
    assert promotions[1].schedule.is_now()


def test_desired_state_existing_schedule(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        SOAK_DAYS: 1,
    })
    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels=set(),
            content_hashes=set([Subscriber.combined_content_hash([subscriber])]),
            failed_mr_check=False,
            is_batchable=False,
            schedule=Schedule(
                data=(datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
            ),
            auto_merge=False,
        )
    ]
    expected_after = datetime.now(tz=timezone.utc) + timedelta(hours=11, minutes=59)
    expected_before = datetime.now(tz=timezone.utc) + timedelta(hours=12, minutes=1)

    desired_state = DesiredState(subscribers=[subscriber], open_mrs=open_mrs)

    assert len(desired_state.promotions) == 1
    assert not desired_state.promotions[0].schedule.is_now()
    assert desired_state.promotions[0].schedule.after >= expected_after
    assert desired_state.promotions[0].schedule.after < expected_before


def test_desired_state_existing_and_not_existing_schedule(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    subscriber_a = subscriber_builder({
        SOAK_DAYS: 1,
        DESIRED_REF: "ref-a",
    })
    subscriber_b = subscriber_builder({
        SOAK_DAYS: 1,
        DESIRED_REF: "ref-b",
    })
    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels=set(),
            content_hashes=set([Subscriber.combined_content_hash([subscriber_a])]),
            failed_mr_check=False,
            is_batchable=False,
            schedule=Schedule(
                data=(datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
            ),
            auto_merge=False,
        )
    ]
    expected_after = datetime.now(tz=timezone.utc) + timedelta(hours=11, minutes=59)
    expected_before = datetime.now(tz=timezone.utc) + timedelta(hours=12, minutes=1)

    desired_state = DesiredState(
        subscribers=[subscriber_a, subscriber_b], open_mrs=open_mrs
    )
    promotions = sorted(desired_state.promotions)

    assert len(promotions) == 2
    assert not promotions[0].schedule.is_now()
    assert promotions[0].schedule.after >= expected_after
    assert promotions[0].schedule.after < expected_before

    expected_after = datetime.now(tz=timezone.utc) + timedelta(hours=23, minutes=59)
    expected_before = datetime.now(tz=timezone.utc) + timedelta(days=1, minutes=1)
    assert not promotions[1].schedule.is_now()
    assert promotions[1].schedule.after >= expected_after
    assert promotions[1].schedule.after < expected_before


def test_desired_state_soak_days_passed(
    subscriber_builder: Callable[[Mapping], Subscriber],
) -> None:
    """
    We expect a subscriber to be merged with other subscribers if its soak_days have passed
    """
    subscriber_a = subscriber_builder({
        SOAK_DAYS: 1,
        DESIRED_REF: "ref-a",
        CHANNEL: {"channel-a": {}, "channel-b": {}},
    })
    subscriber_b = subscriber_builder({
        DESIRED_REF: "ref-b",
        CHANNEL: {"channel-a": {}, "channel-b": {}},
    })
    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels=set(),
            content_hashes=set([Subscriber.combined_content_hash([subscriber_a])]),
            failed_mr_check=False,
            is_batchable=True,
            schedule=Schedule.now(),
            auto_merge=True,
        )
    ]

    desired_state = DesiredState(
        subscribers=[subscriber_a, subscriber_b], open_mrs=open_mrs
    )

    assert len(desired_state.promotions) == 1
    assert desired_state.promotions[0].schedule.is_now()
    assert desired_state.promotions[0].content_hashes == set([
        Subscriber.combined_content_hash(subscribers=[subscriber_a, subscriber_b])
    ])
