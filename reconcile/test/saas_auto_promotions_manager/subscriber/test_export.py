from collections.abc import Callable, Mapping
from typing import Any

from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


def test_export(
    subscriber_builder: Callable[[Mapping[str, Any]], Subscriber],
) -> None:
    subscriber = subscriber_builder({})
    data = subscriber.to_exportable_dict()
    decoded_subscriber = Subscriber.from_exported_dict(data)

    assert decoded_subscriber == subscriber
