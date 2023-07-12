from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

from .data_keys import (
    CHANNELS,
    CUR_CONFIG_HASHES,
    CUR_SUBSCRIBER_REF,
    REAL_WORLD_SHA,
    SUCCESSFUL_DEPLOYMENT,
    USE_TARGET_CONFIG_HASH,
)


def test_no_change(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
):
    subscriber = subscriber_builder(
        {
            USE_TARGET_CONFIG_HASH: False,
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                    },
                    "publisher_b": {
                        REAL_WORLD_SHA: "current_sha",
                    },
                },
                "channel-b": {
                    "publisher_c": {
                        REAL_WORLD_SHA: "current_sha",
                    },
                },
            },
        }
    )
    subscriber.compute_desired_state()
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_moving_ref(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
):
    subscriber = subscriber_builder(
        {
            USE_TARGET_CONFIG_HASH: False,
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                    },
                    "publisher_b": {
                        REAL_WORLD_SHA: "new_sha",
                    },
                },
                "channel-b": {
                    "publisher_c": {
                        REAL_WORLD_SHA: "new_sha",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == []


def test_moving_ref_mismatch(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
):
    subscriber = subscriber_builder(
        {
            USE_TARGET_CONFIG_HASH: False,
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                    },
                    "publisher_b": {
                        REAL_WORLD_SHA: "other_new_sha",
                    },
                },
                "channel-b": {
                    "publisher_c": {
                        REAL_WORLD_SHA: "new_sha",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []


def test_moving_ref_bad_deployment(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
):
    subscriber = subscriber_builder(
        {
            USE_TARGET_CONFIG_HASH: False,
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                    },
                    "publisher_b": {
                        REAL_WORLD_SHA: "new_sha",
                        SUCCESSFUL_DEPLOYMENT: False,
                    },
                },
                "channel-b": {
                    "publisher_c": {
                        REAL_WORLD_SHA: "new_sha",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == []
