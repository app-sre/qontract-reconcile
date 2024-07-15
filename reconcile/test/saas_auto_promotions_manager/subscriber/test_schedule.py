from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    Subscriber,
)


def test_single_publisher_in_schedule(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "SCHEDULE": "* * * * *",
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # We are within cron expression -> promote new ref
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_single_publisher_outside_schedule(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        # We stay away from datetime mocking for now as it conflicts with other gates
        # Very unlikely we have a test running at exactly this time
        "SCHEDULE": "1 1 1 1 1",
        "USE_TARGET_CONFIG_HASH": False,
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # We are outside of our cron expression-> do not promote
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []
