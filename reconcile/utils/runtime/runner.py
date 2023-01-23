import logging
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Protocol,
)

from reconcile.utils import gql
from reconcile.utils.runtime.desired_state_diff import (
    DesiredStateDiff,
    build_desired_state_diff,
)
from reconcile.utils.runtime.integration import QontractReconcileIntegration


class DesiredStateProvider(Protocol):
    def current_desired_state(self) -> dict[str, Any]:
        ...

    def previous_desired_state(self) -> dict[str, Any]:
        ...


@dataclass
class IntegrationRunConfiguration:
    integration: QontractReconcileIntegration
    valdiate_schemas: bool
    dry_run: bool
    early_exit_compare_sha: Optional[str]
    gql_sha_url: bool
    print_url: bool
    run_args: Any
    run_kwargs: Any

    def main_bundle_desired_state(self) -> dict[str, Any]:
        self.switch_to_main_bundle()
        return self.integration.get_early_exit_desired_state(
            *self.run_args, **self.run_kwargs
        )

    def comparison_bundle_desired_state(self) -> dict[str, Any]:
        self.switch_to_comparison_bundle()
        data = self.integration.get_early_exit_desired_state(
            *self.run_args, **self.run_kwargs
        )
        self.switch_to_main_bundle()
        return data

    def switch_to_main_bundle(self, validate_schemas: Optional[bool] = None) -> None:
        final_validate_schemas = (
            validate_schemas if validate_schemas is not None else self.valdiate_schemas
        )
        gql.init_from_config(
            autodetect_sha=self.gql_sha_url,
            integration=self.integration.name,
            validate_schemas=final_validate_schemas,
            print_url=self.print_url,
        )

    def switch_to_comparison_bundle(
        self, validate_schemas: Optional[bool] = None
    ) -> None:
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
) -> Optional[DesiredStateDiff]:
    if not run_cfg.early_exit_compare_sha:
        return None

    # get desired state from comparison bundle
    try:
        previous_desired_state = run_cfg.comparison_bundle_desired_state()
    except NotImplementedError:
        logging.warning(f"{run_cfg.integration.name} does not support early exit.")
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
    except Exception:
        logging.exception("Failed to fetch desired state for current bundle")
        return None

    return build_desired_state_diff(
        run_cfg.integration.get_desired_state_shard_config(),
        previous_desired_state,
        current_desired_state,
    )


def run_integration_cfg(run_cfg: IntegrationRunConfiguration) -> None:
    if run_cfg.dry_run:
        desired_state_diff = get_desired_state_diff(run_cfg)
        run_cfg.switch_to_main_bundle()
        _integration_dry_run(
            run_cfg.integration,
            desired_state_diff,
            *run_cfg.run_args,
            **run_cfg.run_kwargs,
        )
    else:
        run_cfg.switch_to_main_bundle()
        _integration_wet_run(
            run_cfg.integration, *run_cfg.run_args, **run_cfg.run_kwargs
        )


def _integration_wet_run(
    integration: QontractReconcileIntegration, *run_args: Any, **run_kwargs: Any
) -> None:
    integration.run(False, *run_args, **run_kwargs)


def _integration_dry_run(
    integration: QontractReconcileIntegration,
    desired_state_diff: Optional[DesiredStateDiff],
    *run_args: Any,
    **run_kwargs: Any,
) -> None:

    # if the integration can exit early, do so ...
    if desired_state_diff and desired_state_diff.can_exit_early():
        logging.debug("No changes in desired state. Exit PR check early.")
        return

    # if not, we run the integration in full
    integration.run(True, *run_args, **run_kwargs)
