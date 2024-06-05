import json
from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.utils.promotion_state import (
    PromotionData,
    PromotionState,
)
from reconcile.utils.state import State


def test_key_exists_v1(s3_state_builder: Callable[[Mapping], State]) -> None:
    state = s3_state_builder({
        "ls": ["/promotions_v2/channel/uid/sha"],
        "get": {
            "promotions_v2/channel/uid/sha": {
                "success": True,
                "target_config_hash": "hash",
                "saas_file": "saas_file",
                "check_in": "2024-04-30 13:47:31.722437+00:00",
            }
        },
    })
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", target_uid="uid"
    )
    assert deployment_info == PromotionData(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
        check_in="2024-04-30 13:47:31.722437+00:00",
    )
    state.ls.assert_called_once_with()  # type: ignore[attr-defined]
    state.get.assert_called_once_with("promotions_v2/channel/uid/sha")  # type: ignore[attr-defined]


def test_key_exists_v2(s3_state_builder: Callable[[Mapping], State]) -> None:
    state = s3_state_builder({
        "ls": ["/promotions_v2/channel/uid/sha"],
        "get": {
            "promotions_v2/channel/uid/sha": {
                "success": True,
                "target_config_hash": "hash",
                "saas_file": "saas_file",
            }
        },
    })
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", target_uid="uid"
    )
    assert deployment_info == PromotionData(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
    )
    state.ls.assert_called_once_with()  # type: ignore[attr-defined]
    state.get.assert_called_once_with("promotions_v2/channel/uid/sha")  # type: ignore[attr-defined]


def test_key_does_not_exist(s3_state_builder: Callable[[Mapping], State]) -> None:
    state = s3_state_builder({
        "ls": [],
        "get": {},
    })
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", target_uid="uid"
    )
    assert deployment_info is None
    state.ls.assert_called_once_with()  # type: ignore[attr-defined]
    state.get.assert_not_called()  # type: ignore[attr-defined]


def test_key_does_not_exist_locally(
    s3_state_builder: Callable[[Mapping], State],
) -> None:
    state = s3_state_builder({
        "ls": [],
        "get": {
            "promotions_v2/channel/uid/sha": {
                "success": True,
                "target_config_hash": "hash",
                "saas_file": "saas_file",
            }
        },
    })
    deployment_state = PromotionState(state=state)
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", target_uid="uid", pre_check_sha_exists=False
    )
    assert deployment_info == PromotionData(
        success=True, target_config_hash="hash", saas_file="saas_file"
    )
    state.ls.assert_not_called()  # type: ignore[attr-defined]
    state.get.assert_called_once_with("promotions_v2/channel/uid/sha")  # type: ignore[attr-defined]


def test_publish_info(s3_state_builder: Callable[[Mapping], State]) -> None:
    state = s3_state_builder({
        "ls": [],
        "get": {},
    })
    deployment_state = PromotionState(state=state)
    promotion_info = PromotionData(
        success=True,
        target_config_hash="some_hash",
        saas_file="some_saas",
        check_in="2024-04-30 13:47:31.722437+00:00",
    )
    deployment_state.publish_promotion_data(
        channel="channel",
        sha="sha",
        target_uid="uid",
        data=promotion_info,
    )
    deployment_state._state.add.assert_called_once_with(  # type: ignore[attr-defined]
        "promotions_v2/channel/uid/sha", promotion_info.dict(), force=True
    )


def test_promotion_data_json_serializable() -> None:
    """
    We store promotion data as json in s3
    """
    promotion_data = PromotionData(
        success=True,
        target_config_hash="some_hash",
        saas_file="some_saas",
        check_in="2024-04-30 13:47:31.722437+00:00",
    )
    json.dumps(promotion_data.dict())


def test_promotion_data_cache(s3_state_builder: Callable[[Mapping], State]) -> None:
    check_in = "2024-04-17 13:47:31.722437+00:00"
    state = s3_state_builder({
        "ls": [],
        "get": {
            "promotions_v2/channel/uid/sha": {
                "success": True,
                "target_config_hash": "hash",
                "saas_file": "saas_file",
                "check_in": check_in,
            }
        },
    })
    deployment_state = PromotionState(state=state)

    # Fetch first time -> not in cache yet
    deployment_info_first = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        target_uid="uid",
        pre_check_sha_exists=False,
        use_cache=True,
    )

    # Fetch second time -> should be in cache
    deployment_info_second = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        target_uid="uid",
        pre_check_sha_exists=False,
        use_cache=True,
    )

    assert deployment_info_first == deployment_info_second
    assert deployment_info_first == PromotionData(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
        check_in=check_in,
    )

    state.get.assert_called_once_with("promotions_v2/channel/uid/sha")  # type: ignore[attr-defined]
    state.ls.assert_not_called()  # type: ignore[attr-defined]


def test_promotion_data_disabled_cache_by_default(
    s3_state_builder: Callable[[Mapping], State],
) -> None:
    check_in = "2024-04-17 13:47:31.722437+00:00"
    state = s3_state_builder({
        "ls": [],
        "get": {
            "promotions_v2/channel/uid/sha": {
                "success": True,
                "target_config_hash": "hash",
                "saas_file": "saas_file",
                "check_in": check_in,
            }
        },
    })
    deployment_state = PromotionState(state=state)

    # Fetch first time -> not in cache yet
    deployment_info_first = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        target_uid="uid",
        pre_check_sha_exists=False,
    )

    # Fetch second time -> disabled cache
    deployment_info_second = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        target_uid="uid",
        pre_check_sha_exists=False,
        use_cache=False,
    )

    expected_promotion = PromotionData(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
        check_in=check_in,
    )

    assert deployment_info_first == expected_promotion
    assert deployment_info_second == expected_promotion

    assert state.get.call_count == 2  # type: ignore[attr-defined]
    state.get.assert_called_with("promotions_v2/channel/uid/sha")  # type: ignore[attr-defined]
    state.ls.assert_not_called()  # type: ignore[attr-defined]
