from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    SAPM_VERSION,
    VERSION_REF,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    Subscriber,
)
from reconcile.utils.vcs import VCS, MRCheckStatus

from .data_keys import (
    DESCRIPTION,
    HAS_CONFLICTS,
    LABELS,
    OPEN_MERGE_REQUESTS,
    PIPELINE_RESULTS,
    SUBSCRIBER_BATCHABLE,
    SUBSCRIBER_CHANNELS,
    SUBSCRIBER_CONTENT_HASH,
    SUBSCRIBER_DESIRED_CONFIG_HASHES,
    SUBSCRIBER_DESIRED_REF,
    SUBSCRIBER_TARGET_NAMESPACE,
    SUBSCRIBER_TARGET_PATH,
)


@pytest.fixture
def mr_builder() -> Callable[[Mapping], ProjectMergeRequest]:
    def builder(data: Mapping) -> ProjectMergeRequest:
        mr = create_autospec(spec=ProjectMergeRequest)
        if CONTENT_HASHES in data:
            # Generate with valid defaults
            mr.attributes = {
                "labels": [SAPM_LABEL],
                "description": f"""
                {PROMOTION_DATA_SEPARATOR}
                {VERSION_REF}: {data.get(VERSION_REF, SAPM_VERSION)}
                {CHANNELS_REF}: {data.get(SUBSCRIBER_CHANNELS, "some_channel")}
                {CONTENT_HASHES}: {data.get(SUBSCRIBER_CONTENT_HASH, "content_hash")}
                {IS_BATCHABLE}: {data.get(SUBSCRIBER_BATCHABLE, "True")}
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
    mr_builder: Callable[[Mapping], ProjectMergeRequest],
) -> Callable[[Mapping], tuple[VCS, list[ProjectMergeRequest]]]:
    def builder(data: Mapping) -> tuple[VCS, list[ProjectMergeRequest]]:
        vcs = create_autospec(spec=VCS)
        open_mrs: list[ProjectMergeRequest] = []
        for d in data.get(OPEN_MERGE_REQUESTS, []):
            open_mrs.append(mr_builder(d))
        vcs.get_open_app_interface_merge_requests.side_effect = [open_mrs]
        vcs.get_gitlab_mr_check_status.side_effect = data.get(
            PIPELINE_RESULTS, [MRCheckStatus.SUCCESS] * 100
        )
        return (vcs, open_mrs)

    return builder


@pytest.fixture
def mr_parser_builder() -> Callable[[Mapping], MRParser]:
    def builder(data: Iterable[OpenMergeRequest]) -> MRParser:
        mr_parser = create_autospec(spec=MRParser)
        mr_parser.retrieve_open_mrs.side_effect = [data]
        return mr_parser

    return builder


@pytest.fixture
def subscriber_builder(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
):
    def builder(data: Mapping) -> Subscriber:
        subscriber = Subscriber(
            saas_name="",
            template_name="",
            target_namespace=saas_target_namespace_builder(
                data.get(SUBSCRIBER_TARGET_NAMESPACE, {})
            ),
            ref="",
            target_file_path=data.get(SUBSCRIBER_TARGET_PATH, ""),
            use_target_config_hash=True,
        )
        subscriber.desired_hashes = data.get(SUBSCRIBER_DESIRED_CONFIG_HASHES, [])
        subscriber.desired_ref = data.get(SUBSCRIBER_DESIRED_REF, "")
        for channel in data.get(SUBSCRIBER_CHANNELS, []):
            subscriber.channels.append(
                Channel(
                    name=channel,
                    publishers=[],
                )
            )
        return subscriber

    return builder


@pytest.fixture
def renderer() -> Renderer:
    return create_autospec(spec=Renderer)
