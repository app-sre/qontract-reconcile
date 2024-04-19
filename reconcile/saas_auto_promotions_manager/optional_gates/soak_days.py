from collections.abc import Iterable
from datetime import datetime

from reconcile.saas_auto_promotions_manager.state import IntegrationState
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


class SoakDaysGate:
    def __init__(self, state: IntegrationState):
        self._state = state

    def filter(self, subscribers: Iterable[Subscriber]) -> list[Subscriber]:
        passing_subscribers: list[Subscriber] = []

        for subscriber in subscribers:
            first_seen = datetime.fromtimestamp(
                self._state.first_seen(subscriber=subscriber)
            )
            now = datetime.now()
            # TODO: should be <= or < ?
            if (now - first_seen).days < subscriber.soak_days:
                continue
            passing_subscribers.append(subscriber)
        return passing_subscribers
