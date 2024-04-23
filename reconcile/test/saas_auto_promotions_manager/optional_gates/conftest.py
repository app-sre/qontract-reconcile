from collections.abc import Callable

import pytest

from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


@pytest.fixture
def subscriber_builder() -> Callable[[], Subscriber]:
    def builder() -> Subscriber:
        subscriber = Subscriber(
            ref="ref-1",
            soak_days=2,
            saas_name="saas-1",
            target_file_path="target-file-path-1",
            target_namespace="target-namespace-1",
            template_name="template-1",
            uid="uid-1",
            use_target_config_hash=True,
        )
        subscriber.desired_ref = "desired-ref-1"
        return subscriber

    return builder
