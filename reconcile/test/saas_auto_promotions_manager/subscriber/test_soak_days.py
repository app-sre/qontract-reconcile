from collections.abc import (
    Callable,
    Mapping,
)
from datetime import UTC, datetime, timedelta
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    Subscriber,
)


def test_single_publisher_soak_days_not_passed(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC),
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # Soak days not passed, so no ref change
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_single_publisher_soak_days_passed(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(days=1, minutes=1),
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # Soak days passed -> new ref up for promotion
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_multiple_publisher_accumulated_soak_days_not_passed(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=11),
                }
            },
            "channel-b": {
                "publisher_b": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=11),
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # Accumulated soak days did not pass -> no new ref
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_multiple_publisher_accumulated_soak_days_passed(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a1": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=8),
                },
                "publisher_a2": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=8),
                },
            },
            "channel-b": {
                "publisher_b": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=8),
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # Accumulated soak days passed -> new ref up for promotion
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []
