from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS

from .data_keys import (
    OPEN_MERGE_REQUESTS,
    SUBSCRIBER_CONTENT_HASH,
    SUBSCRIBER_DESIRED_CONFIG_HASHES,
    SUBSCRIBER_DESIRED_REF,
    SUBSCRIBER_NAMESPACE_REF,
    SUBSCRIBER_TARGET_PATH,
)


def test_no_related_open_merge_request(
    vcs_builder: Callable[[Mapping], VCS],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            SUBSCRIBER_NAMESPACE_REF: "namespace1",
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
        }
    )

    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    SUBSCRIBER_CONTENT_HASH: "oldcontent",
                    SUBSCRIBER_NAMESPACE_REF: "other-namespace",
                    SUBSCRIBER_TARGET_PATH: subscriber.target_file_path,
                }
            ]
        }
    )

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    merge_request_manager.housekeeping()
    merge_request_manager.process_subscriber(subscriber=subscriber)

    # The open MR is not for the same target -> should not close anything
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_called_once()  # type: ignore[attr-defined]


def test_close_old_content(
    vcs_builder: Callable[[Mapping], VCS],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            SUBSCRIBER_NAMESPACE_REF: "namespace1",
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
        }
    )

    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    SUBSCRIBER_CONTENT_HASH: "oldcontent",
                    SUBSCRIBER_NAMESPACE_REF: subscriber.namespace_file_path,
                    SUBSCRIBER_TARGET_PATH: subscriber.target_file_path,
                }
            ]
        }
    )

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    merge_request_manager.housekeeping()
    merge_request_manager.process_subscriber(subscriber=subscriber)

    # There was is an open MR with old content for that subscriber
    # Close old content and open new MR with new content
    vcs.close_app_interface_mr.assert_called_once()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_called_once()  # type: ignore[attr-defined]


def test_merge_request_already_opened(
    vcs_builder: Callable[[Mapping], VCS],
    renderer: Renderer,
    subscriber_builder: Callable[[Mapping], Subscriber],
):
    subscriber = subscriber_builder(
        {
            SUBSCRIBER_NAMESPACE_REF: "namespace1",
            SUBSCRIBER_TARGET_PATH: "target1",
            SUBSCRIBER_DESIRED_REF: "new_sha",
            SUBSCRIBER_DESIRED_CONFIG_HASHES: [],
        }
    )

    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    SUBSCRIBER_CONTENT_HASH: subscriber.content_hash(),
                    SUBSCRIBER_NAMESPACE_REF: subscriber.namespace_file_path,
                    SUBSCRIBER_TARGET_PATH: subscriber.target_file_path,
                }
            ]
        }
    )

    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    merge_request_manager.housekeeping()
    merge_request_manager.process_subscriber(subscriber=subscriber)

    # There is already an open merge request for this subscriber content
    # Do not open another one
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_not_called()  # type: ignore[attr-defined]
