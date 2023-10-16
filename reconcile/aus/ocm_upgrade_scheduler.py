from abc import ABC
from datetime import datetime
from typing import Optional

from reconcile.aus import base as aus
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.metrics import (
    UPGRADE_BLOCKED_METRIC_VALUE,
    UPGRADE_LONG_RUNNING_METRIC_VALUE,
    UPGRADE_SCHEDULED_METRIC_VALUE,
    UPGRADE_STARTED_METRIC_VALUE,
    AUSClusterVersionRemainingSoakDaysGauge,
)
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import metrics
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    OCM_PRODUCT_ROSA,
)
from reconcile.utils.ocm_base_client import init_ocm_base_client_for_org

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD, OCM_PRODUCT_ROSA]


class OCMClusterUpgradeSchedulerIntegration(
    aus.AdvancedUpgradeSchedulerBaseIntegration, ABC
):
    """
    This flavor of upgrade scheduler has been made abstract to indicate that it
    should not be used directly anymore until its code is removed.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ocm_api = init_ocm_base_client_for_org(org_upgrade_spec.org, self.secret_reader)
        current_state = aus.fetch_current_state(
            ocm_api=ocm_api,
            org_upgrade_spec=org_upgrade_spec,
        )
        version_data_map = aus.get_version_data_map(
            dry_run=dry_run,
            org_upgrade_spec=org_upgrade_spec,
            integration=self.name,
        )
        version_data = version_data_map.get(
            org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
        )

        self.expose_remaining_soak_day_metrics(
            ocm_env=org_upgrade_spec.org.environment.name,
            org_upgrade_spec=org_upgrade_spec,
            version_data=version_data_map.get(
                org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
            ),
            current_state=current_state,
        )

        diffs = aus.calculate_diff(
            current_state, org_upgrade_spec, ocm_api, version_data
        )
        aus.act(dry_run, diffs, ocm_api)

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment
    ) -> dict[str, OrganizationUpgradeSpec]:
        raise NotImplementedError(
            "Don't use ocm-upgrade-scheduler anymore but use: \n"
            "* ocm-label to transfer upgrade policies to OCM subscription labels \n"
            "* advanced-upgrade-service to drive upgrade policies based on OCM subscription labels"
        )

    def expose_remaining_soak_day_metrics(
        self,
        ocm_env: str,
        org_upgrade_spec: OrganizationUpgradeSpec,
        version_data: VersionData,
        current_state: list[aus.AbstractUpgradePolicy],
    ) -> None:
        current_cluster_upgrade_policies = {
            p.cluster.external_id: p for p in current_state
        }
        for spec in org_upgrade_spec.specs:
            upgrades = spec.get_available_upgrades()
            if not upgrades:
                continue

            # calculate the amount every version has soaked. if a version has soaked for
            # multiple workloads, we will pick the minimum soak day value of all workloads
            # relevant on the cluster.
            soaked_versions: dict[str, float] = {}
            for workload in spec.upgrade_policy.workloads:
                for version, soak_days in aus.soaking_days(
                    version_data, upgrades, workload, False
                ).items():
                    soaked_versions[version] = min(
                        soak_days, soaked_versions.get(version, soak_days)
                    )

            current_upgrade = current_cluster_upgrade_policies.get(spec.cluster_uuid)
            for version, metric_value in remaining_soak_day_metric_values_for_cluster(
                spec, soaked_versions, current_upgrade
            ).items():
                metrics.set_gauge(
                    AUSClusterVersionRemainingSoakDaysGauge(
                        integration=self.name,
                        ocm_env=ocm_env,
                        cluster_uuid=spec.cluster.external_id,
                        soaking_version=version,
                    ),
                    metric_value,
                )


def remaining_soak_day_metric_values_for_cluster(
    spec: ClusterUpgradeSpec,
    soaked_versions: dict[str, float],
    current_upgrade: Optional[aus.AbstractUpgradePolicy],
) -> dict[str, float]:
    """
    Calculate what versions and metric values to report for `AUSClusterVersionRemainingSoakDaysGauge`.
    Usually, the remaining soak days for a version are reported but there are some special cases
    where we report negative values to indicate that a version is blocked or an upgrade has been
    scheduled or started.

    Additionally certain versions are not reported when it is not meaningful (e.g. an upgrade will never happen)
    to prevent metric clutter.
    """
    upgrades = spec.get_available_upgrades()
    if not upgrades:
        return {}

    # calculate the remaining soakdays for each upgrade version candidate of the cluster.
    # when a version is soaking, it has a value > 0 and when it soaked enough, the value is 0.
    remaining_soakdays: list[float] = [
        max(
            (spec.upgrade_policy.conditions.soak_days or 0) - soaked_versions.get(v, 0),
            0,
        )
        for v in upgrades
    ]

    # under certain conditions, the remaining soak day value for a version needs to be
    # replaced with special marker values
    version_metrics: dict[str, float] = {}
    for idx, version in reversed(list(enumerate(upgrades))):
        # if an upgrade is `scheduled` or `started`` for the specific version, their respective negative
        # marker values will be used instead of their actual soak days. there are other states than `scheduled`
        # and `started` but the `UpgradePolicy` vanishes too quickly to observe them reliably, when such
        # states are reached.
        if current_upgrade and current_upgrade.version == version:
            if current_upgrade.state == "scheduled":
                remaining_soakdays[idx] = UPGRADE_SCHEDULED_METRIC_VALUE
            elif current_upgrade.state in ("started", "delayed"):
                remaining_soakdays[idx] = UPGRADE_STARTED_METRIC_VALUE
                if current_upgrade.next_run:
                    # if an upgrade runs for over 6 hours, we mark it as a long running upgrade
                    next_run = datetime.strptime(
                        current_upgrade.next_run, "%Y-%m-%dT%H:%M:%SZ"
                    )
                    now = datetime.utcnow()
                    hours_ago = (now - next_run).total_seconds() / 3600
                    if hours_ago >= 6:
                        remaining_soakdays[idx] = UPGRADE_LONG_RUNNING_METRIC_VALUE
        elif spec.version_blocked(version):
            # if a version is blocked, we will still report it but with a dedicated negative marker value
            remaining_soakdays[idx] = UPGRADE_BLOCKED_METRIC_VALUE

        # we are intentionally not reporting versions that still soak or soaked enough when
        # there is a later version that also soaked enough. the later one will be picked
        # for an upgrade over the older one anyways.
        if remaining_soakdays[idx] >= 0 and any(
            later_version_remaining_soak_days
            in (
                0,
                UPGRADE_SCHEDULED_METRIC_VALUE,
                UPGRADE_STARTED_METRIC_VALUE,
                UPGRADE_LONG_RUNNING_METRIC_VALUE,
            )
            for later_version_remaining_soak_days in remaining_soakdays[idx + 1 :]
        ):
            continue
        version_metrics[version] = remaining_soakdays[idx]

    return version_metrics
