from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    Subscriber,
)


def test_version_not_blocked(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
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

    # version not blocked -> new ref up for promotion
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_version_blocked(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        "CUR_SUBSCRIBER_REF": "current_sha",
        "USE_TARGET_CONFIG_HASH": False,
        "BLOCKED_VERSIONS": {"new_sha"},
        "CHANNELS": {
            "channel-a": {
                "publisher_a": {
                    "REAL_WORLD_SHA": "new_sha",
                }
            },
        },
    })
    subscriber.compute_desired_state()

    # version blocked -> no change
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []
