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
    NAMESPACE,
    REF,
)


def test_json_path_selector_include(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder({
        NAMESPACE: {
            "path": "/some/namespace.yml",
            "name": "test-namespace",
            "cluster": {
                "name": "test-cluster",
            },
        },
        REF: "new_sha",
        CONFIG_HASHES: [
            ConfigHash(
                channel="channel-a",
                target_config_hash="new_hash",
                parent_saas="parent_saas",
            )
        ],
        CHANNELS: ["channel-a"],
    })
    saas_content, expected = file_contents("json_path_selector_includes")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()


def test_json_path_selector_exclude(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder({
        NAMESPACE: {
            "path": "/some/namespace.yml",
            "name": "test-namespace",
            "cluster": {
                "name": "test-cluster",
            },
        },
        REF: "hyper_sha",
        CONFIG_HASHES: [
            ConfigHash(
                channel="channel-a",
                target_config_hash="hyper_hash",
                parent_saas="parent_saas",
            )
        ],
        CHANNELS: ["channel-a"],
    })
    saas_content, expected = file_contents("json_path_selector_excludes")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()
