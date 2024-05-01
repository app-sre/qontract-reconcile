from collections import defaultdict
from collections.abc import Iterable

from reconcile.saas_auto_promotions_manager.merge_request_manager.batcher import (
    Promotion,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


class DesiredState:
    def __init__(self, subscribers: Iterable[Subscriber]) -> None:
        self.content_hash_to_subscriber: dict[str, list[Subscriber]] = {}
        subscribers_per_channel_combo: dict[str, list[Subscriber]] = defaultdict(list)
        for subscriber in subscribers:
            channel_combo = ",".join([c.name for c in subscriber.channels])
            subscribers_per_channel_combo[channel_combo].append(subscriber)

        desired_promotions: list[Promotion] = []
        for channel_combo, subs in subscribers_per_channel_combo.items():
            combined_content_hash = Subscriber.combined_content_hash(subscribers=subs)
            self.content_hash_to_subscriber[combined_content_hash] = subs
            desired_promotions.append(
                Promotion(
                    content_hashes={combined_content_hash},
                    channels={channel_combo},
                )
            )
        self.promotions = desired_promotions
