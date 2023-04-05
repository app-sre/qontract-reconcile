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
    CONFIG_HASHES,
    NAMESPACE_PATH,
    REF,
)


def test_content_single_target(
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
        }
    )
    saas_content, expected = file_contents("single_target")
    renderer = Renderer()
    result = renderer.render_merge_request_content(
        subscriber=subscriber,
        current_content=saas_content,
    )
    assert result.strip() == expected.strip()
