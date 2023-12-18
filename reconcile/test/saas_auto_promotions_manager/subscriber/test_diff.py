from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import (
    ConfigHash,
    Subscriber,
)

from .data_keys import (
    CUR_CONFIG_HASHES,
    CUR_SUBSCRIBER_REF,
    DESIRED_REF,
    DESIRED_TARGET_HASHES,
)


def test_has_config_hash_diff(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: [
            ConfigHash(
                channel="channel-a",
                parent_saas="publisher_a",
                target_config_hash="pub_a_hash",
            ),
            ConfigHash(
                channel="channel-b",
                parent_saas="publisher_b",
                target_config_hash="pub_b_hash",
            ),
        ],
        DESIRED_REF: "current_sha",
        DESIRED_TARGET_HASHES: [
            ConfigHash(
                channel="channel-a",
                parent_saas="publisher_a",
                target_config_hash="pub_a_hash",
            ),
            ConfigHash(
                channel="channel-b",
                parent_saas="publisher_b",
                target_config_hash="new_hash",
            ),
        ],
    })
    assert subscriber.has_diff()


def test_has_ref_diff(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: [],
        DESIRED_REF: "new_sha",
        DESIRED_TARGET_HASHES: [],
    })
    assert subscriber.has_diff()


def test_no_diff(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    config_hashes = [
        ConfigHash(
            channel="channel-a",
            parent_saas="publisher_a",
            target_config_hash="pub_a_hash",
        ),
        ConfigHash(
            channel="channel-b",
            parent_saas="publisher_b",
            target_config_hash="pub_b_hash",
        ),
    ]
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: config_hashes,
        DESIRED_REF: "current_sha",
        DESIRED_TARGET_HASHES: list(reversed(config_hashes)),
    })
    assert not subscriber.has_diff()


def test_hashes_desired_subset_of_current(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    """
    We do not react on additional current hashes, i.e., SAPM is not responsible
    for deleting dangling hashes -> we only care about desired hashes being in place.
    """
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: [
            ConfigHash(
                channel="channel-a",
                parent_saas="saas-a",
                target_config_hash="hash-a",
            ),
            ConfigHash(
                channel="channel-b",
                parent_saas="saas-b",
                target_config_hash="hash-b",
            ),
        ],
        DESIRED_REF: "current_sha",
        DESIRED_TARGET_HASHES: [
            ConfigHash(
                channel="channel-b",
                parent_saas="saas-b",
                target_config_hash="hash-b",
            ),
        ],
    })
    assert not subscriber.has_diff()


def test_hashes_current_subset_of_desired(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: [
            ConfigHash(
                channel="channel-b",
                parent_saas="saas-b",
                target_config_hash="hash-b",
            ),
        ],
        DESIRED_REF: "current_sha",
        DESIRED_TARGET_HASHES: [
            ConfigHash(
                channel="channel-a",
                parent_saas="saas-a",
                target_config_hash="hash-a",
            ),
            ConfigHash(
                channel="channel-b",
                parent_saas="saas-b",
                target_config_hash="hash-b",
            ),
        ],
    })
    assert subscriber.has_diff()


def test_empty_hashes(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({
        CUR_SUBSCRIBER_REF: "current_sha",
        CUR_CONFIG_HASHES: [],
        DESIRED_REF: "current_sha",
        DESIRED_TARGET_HASHES: [],
    })
    assert not subscriber.has_diff()
