from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import (
    create_autospec,
)

from pytest import raises

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.promotion_state import PromotionData, PromotionState
from tools.saas_promotion_state.saas_promotion_state import (
    SaasPromotionState,
    SaasPromotionStateException,
    SaasPromotionStateMissingException,
)


def test_get_saas_promotion_state(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([
        {
            "path": "/saas1.yml",
            "name": "saas_1",
            "resourceTemplates": [
                {
                    "name": "template_1",
                    "url": "repo1/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace1.yml"},
                            "promotion": {
                                "publish": ["channel-a"],
                            },
                        }
                    ],
                }
            ],
        },
        {
            "path": "/saas2.yml",
            "name": "saas_2",
            "resourceTemplates": [
                {
                    "name": "template_2",
                    "url": "repo2/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace2.yml"},
                            "promotion": {
                                "publish": ["channel-b"],
                                "subscribe": ["channel-a"],
                            },
                        },
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace3.yml"},
                        },
                    ],
                }
            ],
        },
    ])

    expected = PromotionData(
        check_in="test1",
        saas_file="test2",
        success=True,
        target_config_hash="test3",
    )
    promotion_state = create_autospec(spec=PromotionState)
    promotion_state.get_promotion_data.return_value = expected
    saas_promotion_state = SaasPromotionState.create(
        promotion_state=promotion_state, saas_files=saas_files
    )
    result = saas_promotion_state.get(channel="channel-a", sha="main")

    assert result == {"616af45d7fad7f4eea8d52b8b5e8a058cef82ab0": expected}
    promotion_state.get_promotion_data.assert_called_once_with(
        sha="main",
        channel="channel-a",
        use_cache=False,
        target_uid="616af45d7fad7f4eea8d52b8b5e8a058cef82ab0",
        pre_check_sha_exists=False,
    )


def test_set_saas_promotion_state_success(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([{"resourceTemplates": []}])

    current_data = PromotionData(
        check_in="test1",
        saas_file="test2",
        success=False,
        target_config_hash="test3",
    )
    promotion_state = create_autospec(spec=PromotionState)
    promotion_state.get_promotion_data.return_value = current_data
    saas_promotion_state = SaasPromotionState.create(
        promotion_state=promotion_state, saas_files=saas_files
    )
    saas_promotion_state.set_successful(
        channel="test-channel", sha="test-sha", publisher_uid="test-uid"
    )

    promotion_state.get_promotion_data.assert_called_once_with(
        sha="test-sha",
        channel="test-channel",
        use_cache=False,
        target_uid="test-uid",
        pre_check_sha_exists=False,
    )
    promotion_state.publish_promotion_data.assert_called_once_with(
        data=PromotionData(
            check_in="test1",
            saas_file="test2",
            success=True,
            target_config_hash="test3",
        ),
        channel="test-channel",
        sha="test-sha",
        target_uid="test-uid",
    )


def test_set_saas_promotion_state_missing(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([{"resourceTemplates": []}])
    promotion_state = create_autospec(spec=PromotionState)
    promotion_state.get_promotion_data.return_value = None
    saas_promotion_state = SaasPromotionState.create(
        promotion_state=promotion_state, saas_files=saas_files
    )

    with raises(SaasPromotionStateMissingException):
        saas_promotion_state.set_successful(
            channel="test-channel", sha="test-sha", publisher_uid="test-uid"
        )

    promotion_state.get_promotion_data.assert_called_once_with(
        sha="test-sha",
        channel="test-channel",
        use_cache=False,
        target_uid="test-uid",
        pre_check_sha_exists=False,
    )
    promotion_state.publish_promotion_data.assert_not_called()


def test_set_saas_promotion_state_already_successful(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([{"resourceTemplates": []}])

    current_data = PromotionData(
        check_in="test1",
        saas_file="test2",
        success=True,
        target_config_hash="test3",
    )
    promotion_state = create_autospec(spec=PromotionState)
    promotion_state.get_promotion_data.return_value = current_data
    saas_promotion_state = SaasPromotionState.create(
        promotion_state=promotion_state, saas_files=saas_files
    )

    with raises(SaasPromotionStateException):
        saas_promotion_state.set_successful(
            channel="test-channel", sha="test-sha", publisher_uid="test-uid"
        )

    promotion_state.get_promotion_data.assert_called_once_with(
        sha="test-sha",
        channel="test-channel",
        use_cache=False,
        target_uid="test-uid",
        pre_check_sha_exists=False,
    )
    promotion_state.publish_promotion_data.assert_not_called()
