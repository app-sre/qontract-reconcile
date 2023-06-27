from typing import Optional

from reconcile.aus.models import (
    ConfiguredUpgradePolicy,
    ConfiguredUpgradePolicyConditions,
)


def build_upgrade_policy(
    cluster: str,
    cluster_uuid: str,
    workloads: list[str],
    current_version: str,
    soak_days: int,
    schedule: Optional[str] = None,
    sector: Optional[str] = None,
    mutexes: Optional[list[str]] = None,
) -> ConfiguredUpgradePolicy:
    return ConfiguredUpgradePolicy(
        cluster=cluster,
        cluster_uuid=cluster_uuid,
        current_version=current_version,
        conditions=ConfiguredUpgradePolicyConditions(
            soakDays=soak_days,
            sector=sector,
            mutexes=mutexes,
        ),
        workloads=workloads,
        schedule=schedule or "* * * * *",
    )
