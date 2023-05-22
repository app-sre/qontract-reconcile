from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.utils.promotion_state import (
    PromotionData,
    PromotionState,
)
from reconcile.utils.state import State


def test_key_exists_old_format(s3_state_builder: Callable[[Mapping], State]):
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
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", saas_target_uid="saas_target_uid"
    )
    assert deployment_info == PromotionData(
        success=True,
        target_config_hash="hash",
        saas_file="saas_file",
    )


def test_key_exists(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": ["/deployments/channel/saas_target_uid/sha"],
            "get": {
                "deployments/channel/saas_target_uid/sha": {
                    "success": True,
                    "target_config_hash": "hash",
                    "saas_file": "saas_file",
                }
            },
        }
    )
    deployment_state = PromotionState(state=state)
    deployment_state.cache_commit_shas_from_s3()
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", saas_target_uid="saas_target_uid"
    )
    assert deployment_info == PromotionData(
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
    deployment_info = deployment_state.get_promotion_data(
        channel="channel", sha="sha", saas_target_uid="saas_target_uid"
    )
    assert deployment_info is None


def test_key_does_not_exist_locally_old_format(
    s3_state_builder: Callable[[Mapping], State]
):
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
    deployment_info = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        saas_target_uid="saas_target_uid",
        local_lookup=False,
    )
    assert deployment_info == PromotionData(
        success=True, target_config_hash="hash", saas_file="saas_file"
    )


def test_key_does_not_exist_locally(s3_state_builder: Callable[[Mapping], State]):
    state = s3_state_builder(
        {
            "ls": [],
            "get": {
                "deployments/channel/saas_target_uid/sha": {
                    "success": True,
                    "target_config_hash": "hash",
                    "saas_file": "saas_file",
                }
            },
        }
    )
    deployment_state = PromotionState(state=state)
    deployment_info = deployment_state.get_promotion_data(
        channel="channel",
        sha="sha",
        saas_target_uid="saas_target_uid",
        local_lookup=False,
    )
    assert deployment_info == PromotionData(
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
    promotion_info = PromotionData(
        success=True,
        target_config_hash="some_hash",
        saas_file="some_saas",
    )
    deployment_state.publish_promotion_data(
        channel="channel",
        sha="sha",
        saas_target_uid="saas_target_uid",
        data=promotion_info,
    )
    deployment_state._state.add.assert_called_once_with(  # type: ignore[attr-defined]
        "deployments/channel/saas_target_uid/sha", promotion_info.dict(), True
    )
