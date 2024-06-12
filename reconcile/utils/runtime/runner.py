import logging
import sys
from dataclasses import dataclass
from typing import (
    Any,
    TypeVar,
)

from sretoolbox.utils import threaded as sretoolbox_threaded

from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.runtime.desired_state_diff import (
    DesiredStateDiff,
    build_desired_state_diff,
)
from reconcile.utils.runtime.integration import (
    QontractReconcileIntegration,
    RunParams,
)

RunParamsTypeVar = TypeVar("RunParamsTypeVar", bound=RunParams)


@dataclass
class IntegrationRunConfiguration:
    """
    Holds all required context and configuration for an integration run.
    """

    integration: QontractReconcileIntegration
    valdiate_schemas: bool
    """
    Whether to fail an integration if it queries schemas it is not allowed to.
    Allowed schemas are listed in the `/app-sre/integration-1.yml` files.
    """

    dry_run: bool
    """
    Whether to run the integration in dry-run mode.
    An integration running dry-run mode should not take any actions but should
    progress through the integration run as far and deep as possible to highlight
    potential problems with the integration or the configuration data from app-interface.
    """

    early_exit_compare_sha: str | None
    """
    The SHA of the bundle to compare the current desired state against.
    """

    check_only_affected_shards: bool
    """
    Whether to only dry-run the integration on shards that are affected by the
    change in desired state.
    """

    gql_sha_url: bool
    """
    If `False`, it will not use the sha_url endpoint
    of graphql (prevent stopping execution on data reload).
    """

    print_url: bool
    """
    A debug flag to control whether the URL of the GraphQL endpoint in use is printed.
    """

    def main_bundle_desired_state(self) -> dict[str, Any] | None:
        self.switch_to_main_bundle()
        return self.integration.get_early_exit_desired_state()

    def comparison_bundle_desired_state(self) -> dict[str, Any] | None:
        self.switch_to_comparison_bundle()
        data = (  # pylint: disable=assignment-from-none
            self.integration.get_early_exit_desired_state()
        )
        self.switch_to_main_bundle()
        return data

    def switch_to_main_bundle(self, validate_schemas: bool | None = None) -> None:
        final_validate_schemas = (
            validate_schemas if validate_schemas is not None else self.valdiate_schemas
        )
        gql.init_from_config(
            autodetect_sha=self.gql_sha_url,
            integration=self.integration.name,
            validate_schemas=final_validate_schemas,
            print_url=self.print_url,
        )

    def switch_to_comparison_bundle(self, validate_schemas: bool | None = None) -> None:
        final_validate_schemas = (
            validate_schemas if validate_schemas is not None else self.valdiate_schemas
        )
        gql.init_from_config(
            sha=self.early_exit_compare_sha,
            integration=self.integration.name,
            validate_schemas=final_validate_schemas,
            print_url=self.print_url,
        )


def get_desired_state_diff(
    run_cfg: IntegrationRunConfiguration,
) -> DesiredStateDiff | None:
    """
    Calculates the desired state diff between the current bundle and the
    comparison bundle for an integration. If the integration does not support
    early exit, or if no comparison bundle is set, returns None.

    The desired state diff contains information about the early-exit eligibility
    of the integration run, and the affected shards.
    """
    if not run_cfg.early_exit_compare_sha:
        return None

    # get desired state from comparison bundle
    try:
        previous_desired_state = run_cfg.comparison_bundle_desired_state()
        if previous_desired_state is None:
            return None
    except Exception as e:
        logging.exception(
            f"Failed to fetch desired state for comparison bundle {run_cfg.early_exit_compare_sha}",
            e,
        )
        return None

    # get desired state from current bundle
    try:
        current_desired_state = run_cfg.main_bundle_desired_state()
        if current_desired_state is None:
            return None
    except Exception:
        logging.exception("Failed to fetch desired state for current bundle")
        return None

    return build_desired_state_diff(
        run_cfg.integration.get_desired_state_shard_config()
        if run_cfg.check_only_affected_shards
        else None,
        previous_desired_state,
        current_desired_state,
    )


def run_integration_cfg(run_cfg: IntegrationRunConfiguration) -> None:
    """
    Runs an integration with the given configuration, making sure to run it
    in the right mode accoring to `run.cfg.dry_run`.
    """
    if run_cfg.dry_run:
        desired_state_diff = get_desired_state_diff(run_cfg)
        run_cfg.switch_to_main_bundle()
        _integration_dry_run(run_cfg.integration, desired_state_diff)
    else:
        run_cfg.switch_to_main_bundle()
        _integration_wet_run(run_cfg.integration)


def _integration_wet_run(
    integration: QontractReconcileIntegration[RunParamsTypeVar],
) -> None:
    """
    Runs an integration in wet mode, i.e. not in dry-run mode.
    """
    integration.run(False)


def _integration_dry_run(
    integration: QontractReconcileIntegration[RunParamsTypeVar],
    desired_state_diff: DesiredStateDiff | None,
) -> None:
    """
    Runs an integration in dry-run mode, i.e. not actually making any changes
    but only logging what would have been done.

    Additionally, if the integration supports early exit, and the desired state
    has not changed, the integration will exit early.

    If the integration supports sharded mode, and the desired state has changed
    only on a subset of shards, the integration will dry-run only on those shards
    only.
    """

    # if the integration can exit early, do so ...
    if desired_state_diff and desired_state_diff.can_exit_early():
        logging.debug("No changes in desired state. Exit PR check early.")
        return

    # we can still try to run the integration in sharded mode on the
    # affected shards only
    if (
        integration.supports_sharded_dry_run_mode()
        and not integration.params_have_shard_info()  # already running in sharded mode?
        and desired_state_diff
        and desired_state_diff.affected_shards
    ):
        affected_shard_list = list(desired_state_diff.affected_shards)
        logging.info(f"run {integration.name} for shards {affected_shard_list}")

        def run_integration_shard(shard: str) -> None:
            sharded_integration = integration.build_integration_instance_for_shard(
                shard
            )
            sharded_integration.run(True)

        # run all shards
        results = sretoolbox_threaded.run(
            run_integration_shard,
            affected_shard_list,
            thread_pool_size=min(len(affected_shard_list), 10),
            return_exceptions=True,
        )

        for shard, result in zip(affected_shard_list, results):
            if _is_task_result_an_error(result):
                logging.error(f"Failed to run integration shard {shard}: {result}")
        failed_shards_count = sum(1 for _ in filter(_is_task_result_an_error, results))
        if failed_shards_count > 0:
            sys.exit(failed_shards_count)
        else:
            return

    # if not, we run the integration in full
    integration.run(True)


def _is_task_result_an_error(result: Any) -> bool:
    """
    Returns True if the current exception is an error, i.e. should be
    considered a failure of the integration run.
    """
    if isinstance(result, SystemExit):
        return result.args[0] != ExitCodes.SUCCESS and result.code is not False
    return isinstance(result, BaseException)
