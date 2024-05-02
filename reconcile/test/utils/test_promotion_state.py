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


def test_key_exists_v1(s3_state_builder: Callable[[Mapping], State]):
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


def test_key_exists_v2(s3_state_builder: Callable[[Mapping], State]):
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


def test_key_does_not_exist(s3_state_builder: Callable[[Mapping], State]):
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


def test_key_does_not_exist_locally(s3_state_builder: Callable[[Mapping], State]):
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
        channel="channel", sha="sha", target_uid="uid", local_lookup=False
    )
    assert deployment_info == PromotionData(
        success=True, target_config_hash="hash", saas_file="saas_file"
    )


def test_publish_info(s3_state_builder: Callable[[Mapping], State]):
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


def test_promotion_data_json_serializable():
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
