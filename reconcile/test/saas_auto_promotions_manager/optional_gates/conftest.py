from collections.abc import Callable

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


@pytest.fixture
def subscriber_builder(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
) -> Callable[[], Subscriber]:
    def builder() -> Subscriber:
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

    return builder
