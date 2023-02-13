from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.utils.deployment_state import (
    DeploymentInfo,
    DeploymentState,
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
    deployment_state = DeploymentState(state=state)
    deployment_info = deployment_state.get_deployment_info(channel="channel", sha="sha")
    assert deployment_info == DeploymentInfo(
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
    deployment_state = DeploymentState(state=state)
    deployment_info = deployment_state.get_deployment_info(channel="channel", sha="sha")
    assert deployment_info is None
