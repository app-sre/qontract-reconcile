from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.utils.promotion_state import (
    PromotionInfo,
    PromotionState,
)
from reconcile.utils.state import State


def test_key_exists(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": ["/promotions/channel/sha"],
            "get": {
                "promotions/channel/sha": {
                    "success": True,
                    "target_config_hash": "hash",
                    "saas_file": "saas_file",
                }
            },
        }
    )
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_info(channel="channel", sha="sha")
    assert deployment_info == PromotionInfo(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
    )


def test_key_does_not_exist(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": [],
            "get": {},
        }
    )
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_info(channel="channel", sha="sha")
    assert deployment_info is None


def test_key_does_not_exist_locally(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": [],
            "get": {
                "promotions/channel/sha": {
                    "success": True,
                    "target_config_hash": "hash",
                    "saas_file": "saas_file",
                }
            },
        }
    )
    deployment_state = PromotionState(state=state)
    deployment_info = deployment_state.get_promotion_info(
        channel="channel", sha="sha", local_lookup=False
    )
    assert deployment_info == PromotionInfo(
        success=True, target_config_hash="hash", saas_file="saas_file"
    )


def test_publish_info(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": [],
            "get": {},
        }
    )
    deployment_state = PromotionState(state=state)
    promotion_info = PromotionInfo(
        success=True,
        target_config_hash="some_hash",
        saas_file="some_saas",
    )
    deployment_state.publish_promotion_info(
        channel="channel",
        sha="sha",
        data=promotion_info,
    )
    deployment_state._state.add.assert_called_once_with(
        "promotions/channel/sha", promotion_info.dict(), True
    )
