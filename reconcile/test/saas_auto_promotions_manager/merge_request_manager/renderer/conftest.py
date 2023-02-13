import os
from collections.abc import (
    Callable,
    Mapping,
)

import pytest

from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

from .data_keys import (
    CONFIG_HASHES,
    NAMESPACE_PATH,
    REF,
)


@pytest.fixture
def file_contents() -> Callable[[str], tuple[str, str]]:
    def contents(case: str) -> tuple[str, str]:
        path = os.path.join(
            os.path.dirname(__file__),
            "files",
        )

        with open(f"{path}/{case}.yml", "r") as f:
            a = f.read().strip()

        with open(f"{path}/{case}.result.yml", "r") as f:
            b = f.read().strip()

        return (a, b)

    return contents


@pytest.fixture
def subscriber_builder() -> Callable[[Mapping], Subscriber]:
    def builder(data: Mapping) -> Subscriber:
        subscriber = Subscriber(
            namespace_file_path=data[NAMESPACE_PATH],
            ref="",
            saas_name="",
            target_file_path="",
            template_name="",
        )
        subscriber.desired_ref = data[REF]
        subscriber.desired_hashes = data[CONFIG_HASHES]
        return subscriber

    return builder
