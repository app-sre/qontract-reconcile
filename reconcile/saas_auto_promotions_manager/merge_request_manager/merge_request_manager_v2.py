import logging
from collections.abc import Iterable

from gitlab.exceptions import GitlabGetError

from reconcile.saas_auto_promotions_manager.merge_request_manager.desired_state import (
    DesiredState,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request import (
    SAPMMR,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.metrics import (
    SAPMClosedMRsCounter as MRClosedCounter,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.metrics import (
    SAPMOpenedMRsCounter as MROpenedCounter,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.metrics import (
    SAPMParallelOpenMRsGauge as ParallelOpenMRGauge,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.reconciler import (
    Addition,
    Reconciler,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils import metrics
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS

BATCH_SIZE_LIMIT = 5

SAPM_LABEL = "SAPM"

MR_DESC = """
This is an auto-promotion triggered by app-interface's [saas-auto-promotions-manager](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/saas_auto_promotions_manager) (SAPM).
This MR promotes all subscribers with auto-promotions for the channel(s) listed below.

Please **do not manually modify** this MR in any way, as it might result in blocking the auto-promotion.

This description is used by SAPM to manage auto-promotions.
"""

MR_DESC_SCHEDULED = """
This is a scheduled auto-promotion triggered by app-interface's [saas-auto-promotions-manager](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/saas_auto_promotions_manager) (SAPM).
This MR promotes all subscribers with auto-promotions for the channel(s) listed below.

Note, that this MR is not set to auto-merge. This MR is scheduled to be merged in the future (see schedule below). You can also skip the schedule and lgtm this MR upfront.
Once the scheduled time is reached, this MR will be closed in favor of a new MR with auto-merge enabled.

Please **do not manually modify** this MR in any way, as it might result in blocking the auto-promotion.

This description is used by SAPM to manage auto-promotions.
"""


class MergeRequestManagerV2:
    """
    Manager for SAPM merge requests.

    This class uses MRParser to fetch current state (currently open MRs).
    This class calculates the desired state (i.e., desired promotions).
    Desired state and current state are given to the Reconciler, which will
    then determine a Diff (Additions and Deletions of MRs).

    This class interacts with VCS to realize the result of the Diff.
    """

    def __init__(
        self, vcs: VCS, mr_parser: MRParser, reconciler: Reconciler, renderer: Renderer
    ):
        self._vcs = vcs
        self._mr_parser = mr_parser
        self._renderer = renderer
        self._reconciler = reconciler
        self._sapm_mrs: list[SAPMMR] = []

    def _render_mr(self, addition: Addition) -> None:
        subs: list[Subscriber] = []
        for content_hash in addition.content_hashes:
            subs.extend(self._desired_state.content_hash_to_subscriber[content_hash])
        content_by_path: dict[str, str] = {}
        has_error = False
        for sub in subs:
            if sub.target_file_path not in content_by_path:
                try:
                    content_by_path[sub.target_file_path] = (
                        self._vcs.get_file_content_from_app_interface_master(
                            file_path=sub.target_file_path
                        )
                    )
                except GitlabGetError as e:
                    if e.response_code == 404:
                        logging.error(
                            "The saas file %s does not exist anylonger. Most likely qontract-server data not in synch. This should resolve soon on its own.",
                            sub.target_file_path,
                        )
                        has_error = True
                        break
                    raise e
            content_by_path[sub.target_file_path] = (
                self._renderer.render_merge_request_content(
                    subscriber=sub,
                    current_content=content_by_path[sub.target_file_path],
                )
            )
        if has_error:
            return

        description_hashes = ",".join(addition.content_hashes)
        description_channels = ",".join(addition.channels)

        desc = MR_DESC if addition.auto_merge else MR_DESC_SCHEDULED

        description = self._renderer.render_description(
            message=desc,
            content_hashes=description_hashes,
            channels=description_channels,
            is_batchable=addition.batchable,
            schedule=addition.schedule,
        )
        title = self._renderer.render_title(
            is_draft=False,
            canary=False,
            channels=description_channels,
            batch_size=len(addition.content_hashes),
            auto_merge=addition.auto_merge,
        )
        logging.info(
            "Open MR for update in channel(s) %s",
            description_channels,
        )
        labels = [SAPM_LABEL]
        if addition.auto_merge:
            labels.append(AUTO_MERGE)
        self._sapm_mrs.append(
            SAPMMR(
                labels=labels,
                content_by_path=content_by_path,
                title=title,
                description=description,
            )
        )

    def reconcile(self, subscribers: Iterable[Subscriber]) -> None:
        current_state = self._mr_parser.retrieve_open_mrs(label=SAPM_LABEL)
        desired_state = DesiredState(subscribers=subscribers, open_mrs=current_state)
        self._desired_state = desired_state

        diff = self._reconciler.reconcile(
            batch_limit=BATCH_SIZE_LIMIT,
            desired_promotions=desired_state.promotions,
            open_mrs=current_state,
        )
        parallel_open_mrs = (
            len(current_state) - len(diff.deletions) + len(diff.additions)
        )
        metrics.set_gauge(ParallelOpenMRGauge(), parallel_open_mrs)
        for deletion in diff.deletions:
            metrics.inc_counter(
                MRClosedCounter(
                    reason=deletion.reason.name,
                ),
            )
            self._vcs.close_app_interface_mr(
                mr=deletion.mr.raw,
                comment=deletion.reason.value,
            )

        for addition in diff.additions:
            metrics.inc_counter(
                MROpenedCounter(
                    is_batchable=addition.batchable,
                    batch_size=len(addition.content_hashes),
                ),
            )
            self._render_mr(addition=addition)

        for rendered_mr in self._sapm_mrs:
            self._vcs.open_app_interface_merge_request(mr=rendered_mr)
