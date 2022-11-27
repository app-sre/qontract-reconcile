from typing import Any
from collections.abc import Mapping


def cluster_disabled_integrations(cluster: Mapping[str, Any]) -> list[str]:
    disabled_ints: list[str] = []
    disable = cluster.get("disable")
    if disable:
        disabled_ints = disable.get("integrations") or []
    return disabled_ints
