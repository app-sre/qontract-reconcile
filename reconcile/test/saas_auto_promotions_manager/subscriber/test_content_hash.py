from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.subscriber import (
    CONTENT_HASH_LENGTH,
    ConfigHash,
    Subscriber,
)

from .data_keys import (
    DESIRED_REF,
    DESIRED_TARGET_HASHES,
    NAMESPACE,
    TARGET_FILE_PATH,
)


def test_can_compute_content_hash(subscriber_builder: Callable[[Mapping], Subscriber]):
    subscribers = [
        subscriber_builder({
            NAMESPACE: {"path": "some_namespace"},
            TARGET_FILE_PATH: "some_saas",
            DESIRED_REF: "new",
            DESIRED_TARGET_HASHES: [
                ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
            ],
        }),
        subscriber_builder({
            NAMESPACE: {"path": "other_namespace"},
            TARGET_FILE_PATH: "other_saas",
            DESIRED_REF: "new",
            DESIRED_TARGET_HASHES: [
                ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
            ],
        }),
    ]
    assert (
        len(Subscriber.combined_content_hash(subscribers=subscribers))
        == CONTENT_HASH_LENGTH
    )


def test_content_hash_is_deterministic(
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscribers = [
        subscriber_builder({
            NAMESPACE: {"path": "some_namespace"},
            TARGET_FILE_PATH: "some_saas",
            DESIRED_REF: "new",
            DESIRED_TARGET_HASHES: [
                ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
            ],
        }),
        subscriber_builder({
            NAMESPACE: {"path": "other_namespace"},
            TARGET_FILE_PATH: "other_saas",
            DESIRED_REF: "old",
            DESIRED_TARGET_HASHES: [
                ConfigHash(channel="h", target_config_hash="i", parent_saas="j"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
            ],
        }),
    ]
    hashes = set()
    for _ in range(3):
        hashes.add(Subscriber.combined_content_hash(subscribers=subscribers))
    assert len(hashes) == 1


def test_content_hash_differs(subscriber_builder: Callable[[Mapping], Subscriber]):
    subscriber_a = subscriber_builder({
        NAMESPACE: {"path": "some_namespace"},
        TARGET_FILE_PATH: "some_saas",
        DESIRED_REF: "new",
        DESIRED_TARGET_HASHES: [
            ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
            ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
        ],
    })

    subscriber_b = subscriber_builder({
        NAMESPACE: {"path": "some_namespace"},
        TARGET_FILE_PATH: "some_other_saas",
        DESIRED_REF: "new",
        DESIRED_TARGET_HASHES: [
            ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
        ],
    })

    assert Subscriber.combined_content_hash([
        subscriber_a
    ]) != Subscriber.combined_content_hash([subscriber_b])


def test_content_hash_equals(subscriber_builder: Callable[[Mapping], Subscriber]):
    subscriber_a = subscriber_builder({
        NAMESPACE: {"path": "some_namespace"},
        TARGET_FILE_PATH: "some_saas",
        DESIRED_REF: "new",
        DESIRED_TARGET_HASHES: [
            ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
            ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
            ConfigHash(channel="h", target_config_hash="i", parent_saas="j"),
            ConfigHash(channel="k", target_config_hash="l", parent_saas="m"),
        ],
    })
    subscriber_b = subscriber_builder({
        NAMESPACE: {"path": "some_namespace"},
        TARGET_FILE_PATH: "some_saas",
        DESIRED_REF: "new",
        DESIRED_TARGET_HASHES: list(
            reversed([
                ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
                ConfigHash(channel="h", target_config_hash="i", parent_saas="j"),
                ConfigHash(channel="k", target_config_hash="l", parent_saas="m"),
            ])
        ),
    })

    assert Subscriber.combined_content_hash([
        subscriber_a,
        subscriber_b,
    ]) == Subscriber.combined_content_hash([subscriber_b, subscriber_a])
