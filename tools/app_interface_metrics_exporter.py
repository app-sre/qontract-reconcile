import click
from pydantic import BaseModel

from reconcile.cli import (
    config_file,
    dry_run,
    log_level,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils import metrics
from reconcile.utils.metrics import GaugeMetric
from reconcile.utils.runtime.environment import init_env


class OverviewBaseMetric(BaseModel):
    "Base class for overview metrics"

    integration: str


class OverviewClustersGauge(OverviewBaseMetric, GaugeMetric):
    "Overview of clusters"

    @classmethod
    def name(cls) -> str:
        return "app_interface_clusters"


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
    clusters = get_clusters()
    metrics.set_gauge(
        OverviewClustersGauge(
            integration="app-interface-metrics-exporter",
        ),
        len(clusters),
    )


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
