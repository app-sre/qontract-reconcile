import os
from collections.abc import (
    Callable,
    Mapping,
)

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    Subscriber,
)

from .data_keys import (
    CHANNELS,
    CONFIG_HASHES,
    NAMESPACE,
    REF,
)


@pytest.fixture
def file_contents() -> Callable[[str], tuple[str, str]]:
    def contents(case: str) -> tuple[str, str]:
        path = os.path.join(
            os.path.dirname(__file__),
            "files",
        )

        with open(f"{path}/{case}.yml", "r", encoding="locale") as f:
            a = f.read().strip()

        with open(f"{path}/{case}.result.yml", "r", encoding="locale") as f:
            b = f.read().strip()

        return (a, b)

    return contents


@pytest.fixture
def subscriber_builder(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
) -> Callable[[Mapping], Subscriber]:
    def builder(data: Mapping) -> Subscriber:
        subscriber = Subscriber(
            target_namespace=saas_target_namespace_builder(data.get(NAMESPACE, {})),
            ref="",
            saas_name="",
            target_file_path="",
            template_name="",
            use_target_config_hash=True,
        )
        subscriber.desired_ref = data[REF]
        subscriber.desired_hashes = data[CONFIG_HASHES]
        for channel in data.get(CHANNELS, []):
            subscriber.channels.append(
                Channel(
                    name=channel,
                    publishers=[],
                )
            )
        return subscriber

    return builder
