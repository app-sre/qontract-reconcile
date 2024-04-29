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


def test_content_single_target(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder({
        "NAMESPACE": {"path": "/some/namespace.yml"},
        "DESIRED_REF": "new_sha",
        "DESIRED_TARGET_HASHES": [
            ConfigHash(
                channel="channel-a",
                target_config_hash="new_hash",
                parent_saas="parent_saas",
            )
        ],
    })
    saas_content, expected = file_contents("single_target")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()


def test_must_not_line_wrap(
    file_contents: Callable[[str], tuple[str, str]],
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    namespace_name = "/services/sosososolong/namespaces/loooooooooooooooooooooooooooooooooooooooooooooooooooooooooong.yml"
    subscriber = subscriber_builder({
        "NAMESPACE": {"path": namespace_name},
        "DESIRED_REF": "new_sha",
        "DESIRED_TARGET_HASHES": [
            ConfigHash(
                channel="channel-a",
                target_config_hash="new_hash",
                parent_saas="parent_saas",
            )
        ],
    })
    saas_content, expected = file_contents("single_target_long_name")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()
