from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    ConfigHash,
    Subscriber,
)

from .data_keys import (
    CHANNELS,
    CONFIG_HASH,
    CUR_CONFIG_HASHES,
    CUR_SUBSCRIBER_REF,
    REAL_WORLD_SHA,
    SUCCESSFUL_DEPLOYMENT,
)


def test_no_change(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "pub_a_hash"),
                ("channel-b", "publisher_b", "pub_b_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "pub_a_hash",
                    }
                },
                "channel-b": {
                    "publisher_b": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "pub_b_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [
            ("channel-a", "publisher_a", "pub_a_hash"),
            ("channel-b", "publisher_b", "pub_b_hash"),
        ]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_moving_ref(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "pub_a_hash"),
                ("channel-b", "publisher_b", "pub_b_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "pub_a_hash",
                    }
                },
                "channel-b": {
                    "publisher_b": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "pub_b_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [
            ("channel-a", "publisher_a", "pub_a_hash"),
            ("channel-b", "publisher_b", "pub_b_hash"),
        ]
    )
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_moving_ref_mismatch(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "pub_a_hash"),
                ("channel-b", "publisher_b", "pub_b_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "pub_a_hash",
                    }
                },
                "channel-b": {
                    "publisher_b": {
                        REAL_WORLD_SHA: "other_new_sha",
                        CONFIG_HASH: "pub_b_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [
            ("channel-a", "publisher_a", "pub_a_hash"),
            ("channel-b", "publisher_b", "pub_b_hash"),
        ]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_moving_ref_bad_deployment(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "pub_a_hash"),
                ("channel-b", "publisher_b", "pub_b_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "pub_a_hash",
                        SUCCESSFUL_DEPLOYMENT: False,
                    }
                },
                "channel-b": {
                    "publisher_b": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "pub_b_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [
            ("channel-a", "publisher_a", "pub_a_hash"),
            ("channel-b", "publisher_b", "pub_b_hash"),
        ]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes
