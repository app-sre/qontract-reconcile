import logging
import re
from collections import defaultdict
from collections.abc import Iterable

from gitlab.exceptions import GitlabGetError

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request import (
    SAPMMR,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    VERSION_REF,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS

ITEM_SEPARATOR = ","

SAPM_LABEL = "SAPM"
SAPM_MR_LABELS = [SAPM_LABEL, AUTO_MERGE]

MR_DESC = """
This is an auto-promotion triggered by app-interface's [saas-auto-promotions-manager](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/saas_auto_promotions_manager) (SAPM).
The channel(s) mentioned in the MR title had an event.
This MR promotes all subscribers with auto-promotions for these channel(s).

Please **do not remove or change any label** from this MR.

Parts of this description are used by SAPM to manage auto-promotions.
"""


class MergeRequestManager:
    """
    Manager for SAPM merge requests. This class
    is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs for subscribers with a state diff.

    The idea is that for every channel combination there exists
    maximum one open MR in app-interface. I.e., all changes for
    a channel combination at a minumum are batched in a single MR.
    The MR description is used to store current state for SAPM.
    Channels can also be batched together into a single MR to reduce the overall
    amount of MRs.
    """

    def __init__(self, vcs: VCS, mr_parser: MRParser, renderer: Renderer):
        self._vcs = vcs
        self._mr_parser = mr_parser
        self._renderer = renderer
        self._version_ref_regex = re.compile(rf"{VERSION_REF}: (.*)$", re.MULTILINE)
        self._content_hash_regex = re.compile(rf"{CONTENT_HASHES}: (.*)$", re.MULTILINE)
        self._channels_regex = re.compile(rf"{CHANNELS_REF}: (.*)$", re.MULTILINE)
        self._is_batchable_regex = re.compile(rf"{IS_BATCHABLE}: (.*)$", re.MULTILINE)
        self._open_mrs: list[OpenMergeRequest] = []
        self._unbatchable_hashes: set[str] = set()

    def _unbatch_failed_mrs(self) -> None:
        """
        We optimistically batch MRs together that didnt run through MR check yet.
        Vast majority of auto-promotion MRs are succeeding checks, so we can stay optimistic.
        In the rare case of an MR failing the check, we want to unbatch it.
        I.e., we open a dedicated MR for each channel in the batched MR, mark the new MRs as non-batchable
        and close the old batched MR. By doing so, we ensure that unrelated MRs are not blocking each other.
        Unbatched MRs are marked and will never be batched again.
        """
        open_mrs_after_unbatching: list[OpenMergeRequest] = []
        for mr in self._open_mrs:
            if mr.is_batchable and mr.failed_mr_check:
                self._vcs.close_app_interface_mr(
                    mr.raw,
                    "Closing this MR because it failed MR check and isn't marked un-batchable yet.",
                )
                # Remember these hashes as unbatchable
                self._unbatchable_hashes.update(mr.content_hashes)
            else:
                open_mrs_after_unbatching.append(mr)
        self._open_mrs = open_mrs_after_unbatching

    def housekeeping(self) -> None:
        self._open_mrs = self._mr_parser.retrieve_open_mrs(label=SAPM_LABEL)
        self._unbatch_failed_mrs()

    def _aggregate_subscribers_per_channel_combo(
        self, subscribers: Iterable[Subscriber]
    ) -> dict[str, list[Subscriber]]:
        subscribers_per_channel_combo: dict[str, list[Subscriber]] = defaultdict(list)
        for subscriber in subscribers:
            channel_combo = ",".join([c.name for c in subscriber.channels])
            subscribers_per_channel_combo[channel_combo].append(subscriber)
        return subscribers_per_channel_combo

    def _merge_request_already_exists(self, channels: str, content_hash: str) -> bool:
        return any(
            True
            for mr in self._open_mrs
            if content_hash in mr.content_hashes and channels in mr.channels
        )

    def create_promotion_merge_requests(
        self, subscribers: Iterable[Subscriber]
    ) -> None:
        """
        Open new MR for channel combinations with new content.
        If there is new content, close any existing MR for that
        channel combination.
        """
        subscribers_per_channel_combo = self._aggregate_subscribers_per_channel_combo(
            subscribers=subscribers
        )
        for channel_combo, subs in subscribers_per_channel_combo.items():
            combined_content_hash = Subscriber.combined_content_hash(subscribers=subs)
            if self._merge_request_already_exists(
                content_hash=combined_content_hash, channels=channel_combo
            ):
                logging.info(
                    "There is already an open merge request for channel(s) %s - skipping",
                    channel_combo,
                )
                continue
            for mr in self._open_mrs:
                if channel_combo not in mr.channels:
                    continue
                if combined_content_hash not in mr.content_hashes:
                    logging.info(
                        "Closing MR %s because it has out-dated content",
                        mr.raw.attributes.get("web_url", "NO_WEBURL"),
                    )
                    self._vcs.close_app_interface_mr(
                        mr=mr.raw,
                        comment="Closing this MR because it has out-dated content.",
                    )
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
                continue

            description = self._renderer.render_description(
                message=MR_DESC,
                content_hashes=combined_content_hash,
                channels=channel_combo,
                is_batchable=combined_content_hash not in self._unbatchable_hashes,
            )
            title = self._renderer.render_title(
                is_draft=False, canary=False, channels=channel_combo
            )
            logging.info(
                "Open MR for update in channel(s) %s",
                channel_combo,
            )
            self._vcs.open_app_interface_merge_request(
                mr=SAPMMR(
                    labels=SAPM_MR_LABELS,
                    content_by_path=content_by_path,
                    title=title,
                    description=description,
                )
            )
