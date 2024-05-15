from __future__ import annotations

from collections.abc import Callable

import click

from reconcile.cli import (
    config_file,
    dry_run,
    log_level,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils import metrics
from reconcile.utils.defer import defer
from reconcile.utils.runtime.environment import init_env
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.vcs import VCS
from tools.saas_metrics_exporter.commit_distance.commit_distance import (
    CommitDistanceFetcher,
)


class SaasMetricsExporter:
    """
    This tool is responsible for exposing/exporting saas metrics and data.

    Note, that by design we store metrics exporters as a tool in the tools directory.
    """

    def __init__(self, vcs: VCS, dry_run: bool) -> None:
        self._vcs = vcs
        self._dry_run = dry_run

    @staticmethod
    def create(dry_run: bool) -> SaasMetricsExporter:
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        vcs = VCS(
            secret_reader=secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
        )
        return SaasMetricsExporter(vcs=vcs, dry_run=dry_run)

    @defer
    def run(
        self,
        env_name: str | None,
        app_name: str | None,
        thread_pool_size: int,
        defer: Callable | None = None,
    ) -> None:
        saas_files = get_saas_files(env_name=env_name, app_name=app_name)
        if defer:
            defer(self._vcs.cleanup)

        commit_distance_fetcher = CommitDistanceFetcher(vcs=self._vcs)
        commit_distance_metrics = commit_distance_fetcher.fetch(
            saas_files=saas_files, thread_pool_size=thread_pool_size
        )
        for m in commit_distance_metrics:
            metrics.set_gauge(
                metric=m.metric,
                value=m.value,
            )


@click.command()
@click.option("--env-name", default=None, help="environment to filter saas files by")
@click.option("--app-name", default=None, help="app to filter saas files by")
@click.option("--thread-pool-size", default=1, help="threadpool size")
@dry_run
@config_file
@log_level
def main(
    env_name: str | None,
    app_name: str | None,
    dry_run: bool,
    thread_pool_size: int,
    configfile: str,
    log_level: str | None,
) -> None:
    init_env(log_level=log_level, config_file=configfile)
    exporter = SaasMetricsExporter.create(dry_run=dry_run)
    exporter.run(
        env_name=env_name, app_name=app_name, thread_pool_size=thread_pool_size
    )


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
