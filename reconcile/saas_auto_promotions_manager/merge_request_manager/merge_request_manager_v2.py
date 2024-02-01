import logging
from collections import defaultdict
from collections.abc import Iterable

from gitlab.exceptions import GitlabGetError

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
    Promotion,
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
SAPM_MR_LABELS = [SAPM_LABEL, AUTO_MERGE]

MR_DESC = """
This is an auto-promotion triggered by app-interface's [saas-auto-promotions-manager](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/saas_auto_promotions_manager) (SAPM).
This MR promotes all subscribers with auto-promotions for the channel(s) listed below.

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
        self._content_hash_to_subscriber: dict[str, list[Subscriber]] = {}
        self._sapm_mrs: list[SAPMMR] = []

    def _aggregate_desired_state(
        self, subscribers: Iterable[Subscriber]
    ) -> list[Promotion]:
        subscribers_per_channel_combo: dict[str, list[Subscriber]] = defaultdict(list)
        for subscriber in subscribers:
            channel_combo = ",".join([c.name for c in subscriber.channels])
            subscribers_per_channel_combo[channel_combo].append(subscriber)

        desired_promotions: list[Promotion] = []
        for channel_combo, subs in subscribers_per_channel_combo.items():
            combined_content_hash = Subscriber.combined_content_hash(subscribers=subs)
            self._content_hash_to_subscriber[combined_content_hash] = subs
            desired_promotions.append(
                Promotion(
                    content_hashes={combined_content_hash},
                    channels={channel_combo},
                )
            )
        return desired_promotions

    def _render_mr(self, addition: Addition) -> None:
        subs: list[Subscriber] = []
        for content_hash in addition.content_hashes:
            subs.extend(self._content_hash_to_subscriber[content_hash])
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

        description = self._renderer.render_description(
            message=MR_DESC,
            content_hashes=description_hashes,
            channels=description_channels,
            is_batchable=addition.batchable,
        )
        title = self._renderer.render_title(
            is_draft=False, canary=False, channels=description_channels
        )
        logging.info(
            "Open MR for update in channel(s) %s",
            description_channels,
        )
        self._sapm_mrs.append(
            SAPMMR(
                labels=SAPM_MR_LABELS,
                content_by_path=content_by_path,
                title=title,
                description=description,
            )
        )

    def reconcile(self, subscribers: Iterable[Subscriber]) -> None:
        current_state = self._mr_parser.retrieve_open_mrs(label=SAPM_LABEL)
        desired_state = self._aggregate_desired_state(subscribers=subscribers)

        diff = self._reconciler.reconcile(
            batch_limit=BATCH_SIZE_LIMIT,
            desired_promotions=desired_state,
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
