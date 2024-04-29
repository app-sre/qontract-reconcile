from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.batcher import (
    Batcher,
    Diff,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    SAPM_LABEL,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenBatcherMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    PROMOTION_DATA_SEPARATOR,
    SAPM_VERSION,
    VERSION_REF,
    Renderer,
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
def mr_parser_builder() -> Callable[[Iterable[OpenBatcherMergeRequest]], MRParser]:
    def builder(data: Iterable[OpenBatcherMergeRequest]) -> MRParser:
        mr_parser = create_autospec(spec=MRParser)
        mr_parser.retrieve_open_mrs.side_effect = [data]
        return mr_parser

    return builder


@pytest.fixture
def reconciler_builder() -> Callable[[Diff], Batcher]:
    def builder(data: Diff) -> Batcher:
        reconciler = create_autospec(spec=Batcher)
        reconciler.reconcile.side_effect = [data]
        return reconciler

    return builder


@pytest.fixture
def renderer() -> Renderer:
    return create_autospec(spec=Renderer)
