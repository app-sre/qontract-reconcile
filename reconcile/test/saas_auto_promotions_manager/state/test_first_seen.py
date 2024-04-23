from collections.abc import Callable

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.state import IntegrationState
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.state import State


@pytest.fixture
def subscriber(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
) -> Subscriber:
    subscriber = Subscriber(
        ref="ref-1",
        soak_days=2,
        saas_name="saas-1",
        target_file_path="target-file-path-1",
        target_namespace=saas_target_namespace_builder({}),
        template_name="template-1",
        uid="uid-1",
        use_target_config_hash=True,
    )
    subscriber.desired_ref = "desired-ref-1"
    return subscriber


def test_already_seen(state: State, subscriber: Subscriber) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    first_seen = integration_state.first_seen(subscriber=subscriber)
    assert first_seen == integration_state.first_seen(subscriber=subscriber)


def test_not_yet_seen(state: State, subscriber: Subscriber) -> None:
    integration_state = IntegrationState(state=state, dry_run=False)

    first_seen = integration_state.first_seen(subscriber=subscriber)

    subscriber.desired_ref = "other-ref"
    # The subscriber has a different ref, so it should be considered new
    assert first_seen < integration_state.first_seen(subscriber=subscriber)
