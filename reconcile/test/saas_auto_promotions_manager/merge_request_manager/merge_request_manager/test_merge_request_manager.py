from collections.abc import (
    Callable,
    Mapping,
)

import pytest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.vcs import VCS

from .data_keys import (
    OPEN_MERGE_REQUESTS,
    SUBSCRIBER_CHANNELS,
    SUBSCRIBER_CONTENT_HASH,
    SUBSCRIBER_DESIRED_CONFIG_HASHES,
    SUBSCRIBER_DESIRED_REF,
    SUBSCRIBER_TARGET_NAMESPACE,
    SUBSCRIBER_TARGET_PATH,
)


def test_close_old_content(
    vcs_builder: Callable[[Mapping], VCS],
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

    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                SUBSCRIBER_CONTENT_HASH: "oldcontent",
                SUBSCRIBER_CHANNELS: "channel-a,channel-b",
            }
        ]
    })

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There was is an open MR with old content for that subscriber
    # Close old content and open new MR with new content
    vcs.close_app_interface_mr.assert_called_once()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_called_once()  # type: ignore[attr-defined]


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
    vcs_builder: Callable[[Mapping], VCS],
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

    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                # Note, that the hash/channel can be embedded within a concatenated string.
                # This is required to allow aggregating multiple MRs into a single MR,
                # while still keeping track of whether the desired content is already part
                # of an MR or not.
                SUBSCRIBER_CONTENT_HASH: f"{hash_prefix}{content_hash}{hash_suffix}",
                SUBSCRIBER_CHANNELS: f"{channel_prefix}{subscriber_channel}{channel_suffix}",
            }
        ]
    })

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There is already an open merge request for this subscriber content
    # Do not open another one
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_not_called()  # type: ignore[attr-defined]


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
    vcs_builder: Callable[[Mapping], VCS],
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

    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                # Note, that the hash/channel can be embedded within a concatenated string.
                # This is required to allow aggregating multiple MRs into a single MR,
                # while still keeping track of whether the desired content is already part
                # of an MR or not.
                SUBSCRIBER_CONTENT_HASH: f"{hash_prefix}{content_hash}{hash_suffix}",
                SUBSCRIBER_CHANNELS: f"{channel_prefix}other-channel{channel_suffix}",
            }
        ]
    })

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    merge_request_manager.create_promotion_merge_requests(subscribers=subscribers)

    # There is already an open merge request for this subscriber content
    # Do not open another one, because the channels do not match
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_called_once()  # type: ignore[attr-defined]
