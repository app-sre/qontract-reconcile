from typing import Mapping, Any


def cluster_disabled_integrations(cluster: Mapping[str, Any]) -> list[str]:
    disabled_ints: list[str] = []
    disable = cluster.get("disable")
    if disable:
        disabled_ints = disable.get("integrations") or []
    return disabled_ints
