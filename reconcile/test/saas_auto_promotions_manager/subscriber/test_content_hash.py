from reconcile.saas_auto_promotions_manager.subscriber import (
    CONTENT_HASH_LENGTH,
    ConfigHash,
    Subscriber,
)


def test_can_compute_content_hash():
    subscriber = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber.desired_ref = "new"
    subscriber.desired_hashes = [
        ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
        ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
    ]
    assert len(subscriber.content_hash()) == CONTENT_HASH_LENGTH


def test_content_hash_is_deterministic():
    subscriber = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber.desired_ref = "new"
    subscriber.desired_hashes = [
        ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
        ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
    ]
    hashes = set()
    for _ in range(3):
        subscriber._content_hash = ""
        hashes.add(subscriber.content_hash())
    assert len(hashes) == 1


def test_content_hash_differs():
    subscriber_a = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber_a.desired_ref = "new"
    subscriber_a.desired_hashes = [
        ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
        ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
    ]

    subscriber_b = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber_b.desired_ref = "new"
    subscriber_b.desired_hashes = [
        ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
    ]

    assert subscriber_a.content_hash() != subscriber_b.content_hash()


def test_content_hash_equals():
    subscriber_a = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber_a.desired_ref = "new"
    subscriber_a.desired_hashes = [
        ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
        ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
        ConfigHash(channel="h", target_config_hash="i", parent_saas="j"),
        ConfigHash(channel="k", target_config_hash="l", parent_saas="m"),
    ]

    subscriber_b = Subscriber(
        ref="some_ref",
        namespace_file_path="some_path",
        saas_name="some_saas",
        target_file_path="some_other_path",
        template_name="template_name",
    )
    subscriber_b.desired_ref = "new"
    subscriber_b.desired_hashes = list(
        reversed(
            [
                ConfigHash(channel="a", target_config_hash="b", parent_saas="c"),
                ConfigHash(channel="e", target_config_hash="f", parent_saas="g"),
                ConfigHash(channel="h", target_config_hash="i", parent_saas="j"),
                ConfigHash(channel="k", target_config_hash="l", parent_saas="m"),
            ]
        )
    )

    for _ in range(3):
        subscriber_a._content_hash = ""
        subscriber_b._content_hash = ""
        assert subscriber_a.content_hash() == subscriber_b.content_hash()
