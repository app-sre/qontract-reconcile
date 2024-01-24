from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.vcs import VCS

from .data_keys import (
    SUBSCRIBER_CHANNELS,
    SUBSCRIBER_DESIRED_CONFIG_HASHES,
    SUBSCRIBER_DESIRED_REF,
    SUBSCRIBER_TARGET_NAMESPACE,
    SUBSCRIBER_TARGET_PATH,
)


def test_close_old_content(
    mr_parser_builder: Callable[[Iterable], MRParser],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscribers = [
        subscriber_builder({
            SUBSCRIBER_TARGET_NAMESPACE: {"path": "namespace1"},
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
            SUBSCRIBER_CHANNELS: ["channel-a", "channel-b"],
        })
    ]

    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(ProjectMergeRequest),
            content_hashes="oldcontent",
            channels="channel-a,channel-b",
            failed_mr_check=False,
            is_batchable=True,
        )
    ]
    mr_parser = mr_parser_builder(open_mrs)
    vcs = create_autospec(spec=VCS)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        mr_parser=mr_parser,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There is an open MR with old content for that subscriber
    # Close old content and open new MR with new content
    vcs.close_app_interface_mr.assert_called_once()
    vcs.open_app_interface_merge_request.assert_called_once()


@pytest.mark.parametrize(
    "hash_prefix, hash_suffix, channel_prefix, channel_suffix",
    [
        ("", "", "", ""),
        ("hashprefix,", "", "", ""),
        ("", ",hashsuffix", "", ""),
        ("", "", "channelprefix,", ""),
        ("", "", "", ",channelsuffix"),
        ("a,", ",b", "c,", ",d"),
    ],
)
def test_merge_request_already_opened(
    mr_parser_builder: Callable[[Iterable], MRParser],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
    hash_prefix: str,
    hash_suffix: str,
    channel_prefix: str,
    channel_suffix: str,
):
    subscriber_channel = "channel-a"
    subscribers = [
        subscriber_builder({
            SUBSCRIBER_TARGET_NAMESPACE: {"path": "namespace1"},
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
            SUBSCRIBER_CHANNELS: [subscriber_channel],
        })
    ]
    content_hash = Subscriber.combined_content_hash(subscribers=subscribers)

    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            content_hashes=f"{hash_prefix}{content_hash}{hash_suffix}",
            channels=f"{channel_prefix}{subscriber_channel}{channel_suffix}",
            is_batchable=True,
            failed_mr_check=False,
        )
    ]
    mr_parser = mr_parser_builder(open_mrs)

    vcs = create_autospec(spec=VCS)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        mr_parser=mr_parser,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There is already an open merge request for this subscriber content
    # Do not open another one
    vcs.close_app_interface_mr.assert_not_called()
    vcs.open_app_interface_merge_request.assert_not_called()


@pytest.mark.parametrize(
    "hash_prefix, hash_suffix, channel_prefix, channel_suffix",
    [
        ("", "", "", ""),
        ("hashprefix,", "", "", ""),
        ("", ",hashsuffix", "", ""),
        ("", "", "channelprefix,", ""),
        ("", "", "", ",channelsuffix"),
        ("a,", ",b", "c,", ",d"),
    ],
)
def test_ignore_unrelated_channels(
    mr_parser_builder: Callable[[Iterable], MRParser],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
    hash_prefix: str,
    hash_suffix: str,
    channel_prefix: str,
    channel_suffix: str,
):
    subscribers = [
        subscriber_builder({
            SUBSCRIBER_TARGET_NAMESPACE: {"path": "namespace1"},
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
            SUBSCRIBER_CHANNELS: ["channel-a"],
        })
    ]
    content_hash = Subscriber.combined_content_hash(subscribers=subscribers)

    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            content_hashes=f"{hash_prefix}{content_hash}{hash_suffix}",
            channels=f"{channel_prefix}other-channel{channel_suffix}",
            is_batchable=True,
            failed_mr_check=False,
        )
    ]
    mr_parser = mr_parser_builder(open_mrs)

    vcs = create_autospec(spec=VCS)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        mr_parser=mr_parser,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There is already an open merge request for this subscriber content
    # Do not open another one, because the channels do not match
    vcs.close_app_interface_mr.assert_not_called()
    vcs.open_app_interface_merge_request.assert_called_once()
