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
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "current_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "current_hash")]
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
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "current_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "current_hash")]
    )
    assert subscriber.desired_ref == "new_sha"
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
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "current_hash",
                        SUCCESSFUL_DEPLOYMENT: False,
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "current_hash")]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_new_config_hash(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "new_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "new_hash")]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_new_config_hash_bad_deployment(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "new_hash",
                        SUCCESSFUL_DEPLOYMENT: False,
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "current_hash")]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_new_config_hash_and_moving_ref(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "new_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "new_hash")]
    )
    assert subscriber.desired_ref == "new_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_new_config_hash_and_moving_ref_and_bad_deployment(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [
                ("channel-a", "publisher_a", "current_hash"),
            ],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "new_sha",
                        CONFIG_HASH: "new_hash",
                        SUCCESSFUL_DEPLOYMENT: False,
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "current_hash")]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes


def test_cur_config_hash_did_not_exist(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
    config_hashes_builder: Callable[
        [Iterable[tuple[str, str, str]]], frozenset[ConfigHash]
    ],
):
    subscriber = subscriber_builder(
        {
            CUR_SUBSCRIBER_REF: "current_sha",
            CUR_CONFIG_HASHES: [],
            CHANNELS: {
                "channel-a": {
                    "publisher_a": {
                        REAL_WORLD_SHA: "current_sha",
                        CONFIG_HASH: "new_hash",
                    }
                },
            },
        }
    )
    subscriber.compute_desired_state()
    expected_config_hashes = config_hashes_builder(
        [("channel-a", "publisher_a", "new_hash")]
    )
    assert subscriber.desired_ref == "current_sha"
    assert subscriber.desired_hashes == expected_config_hashes
