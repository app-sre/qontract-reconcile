from collections.abc import (
    Callable,
    Mapping,
)
from datetime import UTC, datetime, timedelta
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    SOAK_DAYS_BUFFER,
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


def test_single_publisher_soak_days_passed_without_buffer(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    """Soak days technically passed but buffer not met - should NOT promote."""
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

    # Soak days passed but buffer not met -> no promotion
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_single_publisher_soak_days_passed_with_buffer(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    """Soak days + buffer passed - should promote."""
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC)
                    - timedelta(days=1)
                    - SOAK_DAYS_BUFFER
                    - timedelta(minutes=1),
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # Soak days + buffer passed -> new ref up for promotion
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
    """3 publishers * 11h = 33h > 24h + 6h buffer = 30h -> should promote."""
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SOAK_DAYS": 1,
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a1": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=11),
                },
                "publisher_a2": {
                    "REAL_WORLD_SHA": "new_sha",
                    "CHECK_IN": datetime.now(UTC) - timedelta(hours=11),
                },
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

    # Accumulated soak days passed (33h > 30h required) -> new ref up for promotion
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []
