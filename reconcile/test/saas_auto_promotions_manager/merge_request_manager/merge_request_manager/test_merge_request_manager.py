from collections.abc import Callable
from unittest.mock import call, create_autospec

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    MergeRequestManagerV2,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.reconciler import (
    Addition,
    Deletion,
    Diff,
    Reason,
    Reconciler,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.test.saas_auto_promotions_manager.merge_request_manager.merge_request_manager.data_keys import (
    CHANNEL,
    REF,
)
from reconcile.utils.vcs import VCS


def test_reconcile(
    reconciler_builder: Callable[[Diff], Reconciler],
    subscriber_builder: Callable[..., Subscriber],
) -> None:
    vcs = create_autospec(spec=VCS)
    mr_parser = create_autospec(spec=MRParser)
    renderer = create_autospec(spec=Renderer)
    subscribers = [
        subscriber_builder({
            CHANNEL: ["chan1,chan2"],
            REF: "hash1",
        })
    ]
    deletion = Deletion(
        mr=OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels=set(),
            content_hashes=set(),
            failed_mr_check=False,
            is_batchable=True,
        ),
        reason=Reason.NEW_BATCH,
    )

    additions = [
        Addition(
            content_hashes={Subscriber.combined_content_hash(subscribers=subscribers)},
            channels={"chan1,chan2"},
            batchable=True,
        )
    ]

    reconciler = reconciler_builder(
        Diff(
            deletions=[deletion],
            additions=additions,
        )
    )
    manager = MergeRequestManagerV2(
        vcs=vcs,
        mr_parser=mr_parser,
        reconciler=reconciler,
        renderer=renderer,
    )

    manager.reconcile(subscribers=subscribers)

    assert len(manager._sapm_mrs) == len(additions)
    vcs.close_app_interface_mr.assert_has_calls([
        call(deletion.mr.raw, deletion.reason.value),
    ])
    vcs.open_app_interface_merge_request.assert_has_calls([
        call(mr) for mr in manager._sapm_mrs
    ])
