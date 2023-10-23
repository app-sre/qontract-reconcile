import logging
from collections.abc import Mapping

import click
from pydantic import BaseModel

from reconcile.cli import (
    config_file,
    dry_run,
    log_level,
)
from reconcile.typed_queries.app_interface_metrics_exporter.onboarding_status import (
    get_onboarding_status,
)
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.metrics import GaugeMetric
from reconcile.utils.runtime.environment import init_env

INTEGRATION = "app-interface-metrics-exporter"


class OverviewBaseMetric(BaseModel):
    """Base class for overview metrics"""

    integration: str


class OverviewOnboardingStatus(OverviewBaseMetric, GaugeMetric):
    """Overview of onboarding status"""

    status: str

    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_onboarding_status"


def publish_onboarding_status_metrics(
    onboarding_status: Mapping[str, int],
) -> None:
    logging.debug("Publishing onboarding status metrics: %s", onboarding_status)
    for status, count in onboarding_status.items():
        metrics.set_gauge(
            OverviewOnboardingStatus(
                integration=INTEGRATION,
                status=status,
            ),
            count,
        )


@click.command()
@config_file
@dry_run
@log_level
def main(
    configfile: str,
    dry_run: bool,
    log_level: str,
) -> None:
    init_env(log_level=log_level, config_file=configfile)
    onboarding_status = get_onboarding_status(gql.get_api())
    publish_onboarding_status_metrics(onboarding_status)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
