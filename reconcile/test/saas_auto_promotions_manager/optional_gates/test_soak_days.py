from collections.abc import Callable
from time import time
from unittest.mock import create_autospec

from reconcile.saas_auto_promotions_manager.optional_gates.soak_days import SoakDaysGate
from reconcile.saas_auto_promotions_manager.state import IntegrationState
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


def test_soak_days_single_fail(subscriber_builder: Callable[[], Subscriber]) -> None:
    state = create_autospec(spec=IntegrationState)
    state.first_seen.return_value = time()
    soak_days = SoakDaysGate(state=state)
    subscriber_a = subscriber_builder()
    subscriber_a.desired_ref = "a-ref"
    subscriber_a.soak_days = 2

    passed_subscribers = soak_days.filter(
        subscribers=[
            subscriber_a,
        ]
    )
    assert passed_subscribers == []


def test_soak_days_single_pass(subscriber_builder: Callable[[], Subscriber]) -> None:
    state = create_autospec(spec=IntegrationState)
    state.first_seen.return_value = time()
    soak_days = SoakDaysGate(state=state)
    subscriber_a = subscriber_builder()
    subscriber_a.desired_ref = "a-ref"
    subscriber_a.soak_days = 0

    passed_subscribers = soak_days.filter(
        subscribers=[
            subscriber_a,
        ]
    )
    assert passed_subscribers == [subscriber_a]


def test_soak_days_one_pass_one_fail(
    subscriber_builder: Callable[[], Subscriber],
) -> None:
    state = create_autospec(spec=IntegrationState)
    state.first_seen.return_value = time()
    soak_days = SoakDaysGate(state=state)
    subscriber_a = subscriber_builder()
    subscriber_a.desired_ref = "a-ref"
    subscriber_a.soak_days = 1
    subscriber_b = subscriber_builder()
    subscriber_b.desired_ref = "b-ref"
    subscriber_b.soak_days = 0

    passed_subscribers = soak_days.filter(
        subscribers=[
            subscriber_a,
            subscriber_b,
        ]
    )
    assert passed_subscribers == [subscriber_b]
