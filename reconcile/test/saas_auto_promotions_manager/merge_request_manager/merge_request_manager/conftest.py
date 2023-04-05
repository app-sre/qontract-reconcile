from collections.abc import (
    Callable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    CONTENT_HASH,
    NAMESPACE_REF,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    TARGET_FILE_PATH,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS

from .data_keys import (
    DESCRIPTION,
    HAS_CONFLICTS,
    LABELS,
    OPEN_MERGE_REQUESTS,
    SUBSCRIBER_CONTENT_HASH,
    SUBSCRIBER_DESIRED_CONFIG_HASHES,
    SUBSCRIBER_DESIRED_REF,
    SUBSCRIBER_NAMESPACE_REF,
    SUBSCRIBER_TARGET_PATH,
)


@pytest.fixture
def mr_builder() -> Callable[[Mapping], ProjectMergeRequest]:
    def builder(data: Mapping) -> ProjectMergeRequest:
        mr = create_autospec(spec=ProjectMergeRequest)
        if CONTENT_HASH in data:
            # Generate with valid defaults
            mr.attributes = {
                "labels": [SAPM_LABEL],
                "description": f"""
                {PROMOTION_DATA_SEPARATOR}
                {NAMESPACE_REF}: {data.get(SUBSCRIBER_NAMESPACE_REF, "namespace_ref")}
                {TARGET_FILE_PATH}: {data.get(SUBSCRIBER_TARGET_PATH, "target_path")}
                {CONTENT_HASH}: {data.get(SUBSCRIBER_CONTENT_HASH, "content_hash")}
                """,
                "web_url": "http://localhost",
                "has_conflicts": False,
            }
        else:
            mr.attributes = {
                "labels": data.get(LABELS, []),
                "description": data.get(DESCRIPTION, ""),
                "web_url": "http://localhost",
                "has_conflicts": data.get(HAS_CONFLICTS, False),
            }
        return mr

    return builder


@pytest.fixture
def vcs_builder(
    mr_builder: Callable[[Mapping], ProjectMergeRequest]
) -> Callable[[Mapping], VCS]:
    def builder(data: Mapping) -> VCS:
        vcs = create_autospec(spec=VCS)
        open_mrs: list[ProjectMergeRequest] = []
        for d in data.get(OPEN_MERGE_REQUESTS, []):
            open_mrs.append(mr_builder(d))
        vcs.get_open_app_interface_merge_requests.side_effect = [open_mrs]
        return vcs

    return builder


@pytest.fixture
def subscriber_builder() -> Callable[[Mapping], Subscriber]:
    def builder(data: Mapping) -> Subscriber:
        subscriber = Subscriber(
            saas_name="",
            template_name="",
            namespace_file_path=data.get(SUBSCRIBER_NAMESPACE_REF, ""),
            ref="",
            target_file_path=data.get(SUBSCRIBER_TARGET_PATH, ""),
        )
        subscriber.desired_hashes = data.get(SUBSCRIBER_DESIRED_CONFIG_HASHES, [])
        subscriber.desired_ref = data.get(SUBSCRIBER_DESIRED_REF, "")
        return subscriber

    return builder


@pytest.fixture
def renderer() -> Renderer:
    return create_autospec(spec=Renderer)
