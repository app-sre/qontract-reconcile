from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.reconciler import (
    Promotion,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.schedule import (
    Schedule,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


class DesiredState:
    def __init__(
        self, subscribers: Iterable[Subscriber], open_mrs: Iterable[OpenMergeRequest]
    ) -> None:
        """
        TODO:
        - if: subscriber.soak_days -> dedicated MR without auto-merge
            - if schedule exists in open_mrs -> copy schedule
            - else: create new schedule
        - else: auto-merge MR
        """
        self.promotions: list[Promotion] = []
        self._processed_hashes: set[str] = set()
        self._handle_schedules(subscribers=subscribers, open_mrs=open_mrs)

        self.content_hash_to_subscriber: dict[str, list[Subscriber]] = {}
        subscribers_per_channel_combo: dict[str, list[Subscriber]] = defaultdict(list)
        for subscriber in subscribers:
            sub_hash = Subscriber.combined_content_hash(subscribers=[subscriber])
            if sub_hash in self._processed_hashes:
                continue
            self._processed_hashes.add(sub_hash)
            channel_combo = ",".join([c.name for c in subscriber.channels])
            subscribers_per_channel_combo[channel_combo].append(subscriber)

        for channel_combo, subs in subscribers_per_channel_combo.items():
            combined_content_hash = Subscriber.combined_content_hash(subscribers=subs)
            self.content_hash_to_subscriber[combined_content_hash] = subs
            self.promotions.append(
                Promotion(
                    content_hashes={combined_content_hash},
                    channels={channel_combo},
                    # TODO
                    schedule=Schedule(data="2007-08-31T16:47+00:00"),
                )
            )

    def _handle_schedules(
        self, subscribers: Iterable[Subscriber], open_mrs: Iterable[OpenMergeRequest]
    ) -> None:
        for subscriber in subscribers:
            if not subscriber.soak_days:
                continue
            expected_after = datetime.now(tz=timezone.utc) + timedelta(
                days=subscriber.soak_days
            )
            schedule = Schedule(data=expected_after.isoformat())
            channel_combo = ",".join([c.name for c in subscriber.channels])
            content_hash = Subscriber.combined_content_hash(subscribers=[subscriber])
            self.promotions.append(
                Promotion(
                    content_hashes={content_hash},
                    channels={channel_combo},
                    schedule=schedule,
                )
            )
            self._processed_hashes.add(content_hash)
