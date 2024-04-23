from collections.abc import Callable, Mapping
from unittest.mock import create_autospec

import pytest

from reconcile.saas_auto_promotions_manager.publisher import DeploymentInfo, Publisher
from reconcile.utils.state import State


@pytest.fixture
def state() -> State:
    state = create_autospec(spec=State)
    state.get.side_effect = [{}]
    return state


@pytest.fixture
def publisher_builder() -> Callable[[Mapping], Publisher]:
    def builder(data: Mapping) -> Publisher:
        publisher = Publisher(
            ref="",
            repo_url="",
            uid="",
            saas_name=data["saas_name"],
            saas_file_path="",
            app_name="",
            namespace_name=data["namespace_name"],
            cluster_name=data["cluster_name"],
            target_name=data.get("target_name"),
            resource_template_name=data["resource_template_name"],
            publish_job_logs=True,
            has_subscriber=True,
            auth_code=None,
        )
        publisher.commit_sha = data["commit_sha"]
        for k, v in data["deployment_info"].items():
            if v is not None:
                publisher.deployment_info_by_channel[k] = DeploymentInfo(
                    success=v,
                    saas_file="",
                    target_config_hash="",
                )
            else:
                publisher.deployment_info_by_channel[k] = None
        return publisher

    return builder
