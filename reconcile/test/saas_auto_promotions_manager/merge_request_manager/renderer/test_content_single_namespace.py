from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import (
    ConfigHash,
    Subscriber,
)

from .data_keys import (
    CHANNELS,
    CONFIG_HASHES,
    NAMESPACE_PATH,
    REF,
)


def test_content_single_namespace(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            NAMESPACE_PATH: "/some/namespace.yml",
            REF: "new_sha",
            CONFIG_HASHES: [
                ConfigHash(
                    channel="channel-a",
                    target_config_hash="current_hash",
                    parent_saas="parent_saas",
                )
            ],
            CHANNELS: ["channel-a"],
        }
    )
    saas_content, expected = file_contents("single_namespace")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()


def test_content_single_namespace_no_previous_hash(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            NAMESPACE_PATH: "/some/namespace.yml",
            REF: "new_sha",
            CONFIG_HASHES: [
                ConfigHash(
                    channel="channel-a",
                    target_config_hash="new_hash",
                    parent_saas="parent_saas",
                )
            ],
            CHANNELS: ["channel-a"],
        }
    )
    saas_content, expected = file_contents("single_namespace_no_hash")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()


def test_content_single_namespace_no_desired_hash(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            NAMESPACE_PATH: "/some/namespace.yml",
            REF: "new_sha",
            CONFIG_HASHES: [],
            CHANNELS: ["channel-a"],
        }
    )
    saas_content, expected = file_contents("single_namespace_ignore_hash")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()
