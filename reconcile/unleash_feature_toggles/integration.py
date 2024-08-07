import logging
from collections.abc import Callable, Iterable, Sequence, ValuesView
from typing import Any

from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    FeatureToggleUnleashV1,
    UnleashInstanceV1,
    UnleashProjectV1,
)
from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    query as unleash_instances_query,
)
from reconcile.utils import gql
from reconcile.utils.differ import DiffPair, diff_any_iterables, diff_mappings
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.unleash.server import (
    Environment,
    FeatureToggle,
    FeatureToggleType,
    Project,
    TokenAuth,
    UnleashServer,
)

QONTRACT_INTEGRATION = "unleash-feature-toggles"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class UnleashTogglesIntegrationParams(PydanticRunParams):
    instance: str | None


def feature_toggle_equal(c: FeatureToggle, d: FeatureToggleUnleashV1) -> bool:
    """Check if two feature toggles are different, but ignore the actual toggle state."""
    assert d.unleash.q_type  # make mypy happy
    return (
        c.description == d.description
        and c.type == FeatureToggleType[d.unleash.q_type]
        and c.impression_data == bool(d.unleash.impression_data)
    )


class UnleashFeatureToggleException(Exception):
    """Raised when a feature toggle is manually created."""


class UnleashFeatureToggleDeleteError(Exception):
    """Raised when a feature toggle is not marked for deletion."""


class UnleashTogglesIntegration(
    QontractReconcileIntegration[UnleashTogglesIntegrationParams]
):
    """Manage Unleash feature toggles."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query
        return {
            "toggles": [ft.dict() for ft in self.get_unleash_instances(query_func)],
        }

    def get_unleash_instances(
        self, query_func: Callable, instance: str | None = None
    ) -> list[UnleashInstanceV1]:
        """Get all Unleash instances with their projects and feature toggles."""
        instances = [
            ui
            for ui in unleash_instances_query(query_func).instances or []
            if (not instance or ui.name == instance) and ui.admin_token
        ]

        # Set default values for all feature toggles
        for inst in instances:
            for project in inst.projects or []:
                for feature_toggle in project.feature_toggles or []:
                    feature_toggle.unleash.q_type = (
                        feature_toggle.unleash.q_type or "release"
                    )
                    feature_toggle.unleash.impression_data = (
                        feature_toggle.unleash.impression_data or False
                    )
        return instances

    def fetch_current_state(self, client: UnleashServer) -> list[Project]:
        """Fetch the current state of all Unleash projects including their feature toggles."""
        return client.projects(include_feature_toggles=True)

    def validate_unleash_projects(
        self,
        current_projects: Iterable[Project],
        desired_projects: Iterable[UnleashProjectV1],
    ) -> ValuesView[DiffPair[Project, UnleashProjectV1]]:
        """Validate that all projects referenced in the desired state are actually exist."""
        diff = diff_any_iterables(
            current=current_projects,
            desired=desired_projects,
            current_key=lambda c: c.name.lower(),
            desired_key=lambda d: d.name.lower(),
            equal=lambda c, d: c.name.lower() == d.name.lower(),
        )
        if diff.add:
            raise ValueError(f"Non-existing projects: {','.join(diff.add.keys())}")
        return diff.identical.values()

    def _reconcile_feature_toggles(
        self,
        client: UnleashServer,
        instance: UnleashInstanceV1,
        project_id: str,
        dry_run: bool,
        current_state: Sequence[FeatureToggle],
        desired_state: Iterable[FeatureToggleUnleashV1],
    ) -> None:
        """Reconcile the feature toggles themselves."""
        diff = diff_any_iterables(
            current=current_state,
            desired=[d for d in desired_state if d.delete is not True],
            current_key=lambda c: c.name,
            desired_key=lambda d: d.name,
            equal=feature_toggle_equal,
        )
        for add in diff.add.values():
            logging.info(
                f"[{instance.name}/{project_id}] Adding feature toggle {add.name}"
            )
            try:
                assert add.unleash.q_type  # make mypy happy
                feature_type = FeatureToggleType[add.unleash.q_type]
            except KeyError:
                raise ValueError(
                    f"[{instance.name}/{project_id}/{add.name}] Invalid feature toggle type '{add.unleash.q_type}', Possible values are: {', '.join(FeatureToggleType.__members__)}"
                ) from None
            if not dry_run:
                client.create_feature_toggle(
                    project_id=project_id,
                    name=add.name,
                    description=add.description,
                    type=feature_type,
                    impression_data=bool(add.unleash.impression_data),
                )

        for change in diff.change.values():
            logging.info(
                f"[{instance.name}/{project_id}] Changing feature toggle {change.desired.name}"
            )
            try:
                assert change.desired.unleash.q_type  # make mypy happy
                feature_type = FeatureToggleType[change.desired.unleash.q_type]
            except KeyError:
                raise ValueError(
                    f"[{instance.name}/{project_id}/{change.current.name}] Invalid feature toggle type '{change.desired.unleash.q_type}', Possible values are: {', '.join(FeatureToggleType.__members__)}"
                ) from None
            if not dry_run:
                client.update_feature_toggle(
                    project_id=project_id,
                    name=change.current.name,
                    description=change.desired.description,
                    type=feature_type,
                    impression_data=bool(change.desired.unleash.impression_data),
                )

        for delete in diff.delete.values():
            desired_toggle = next(
                (d for d in desired_state if d.name == delete.name and d.delete), None
            )
            if desired_toggle:
                logging.info(
                    f"[{instance.name}/{project_id}] Deleting feature toggle {delete.name}"
                )
                if not dry_run:
                    client.delete_feature_toggle(
                        project_id=project_id,
                        name=delete.name,
                    )
            elif not instance.allow_unmanaged_feature_toggles:
                raise UnleashFeatureToggleDeleteError(
                    f"[{instance.name}/{project_id}] Found unmanaged feature toggles '{[d.name for d in diff.delete.values()]}'"
                )

    def _reconcile_states(
        self,
        client: UnleashServer,
        instance: UnleashInstanceV1,
        project_id: str,
        dry_run: bool,
        current_state: Sequence[FeatureToggle],
        desired_state: Iterable[FeatureToggleUnleashV1],
        available_environments: Iterable[Environment],
    ) -> None:
        """Reconcile the feature toggle states."""
        current_toggle_states = {
            (state.name, env.name): env.enabled
            for state in current_state
            for env in state.environments
        }
        desired_toggle_states = {
            (state.name, env_name): enabled
            for state in desired_state
            for env_name, enabled in (state.unleash.environments or {}).items()
        }

        diff_result = diff_mappings(
            current=current_toggle_states, desired=desired_toggle_states
        )
        for (name, env), pair in diff_result.change.items():
            if env not in available_environments:
                raise ValueError(
                    f"[{instance.name}/{project_id}/{name}] Environment '{env}' does not exist in Unleash!"
                )
            if not dry_run:
                client.set_feature_toggle_state(
                    project_id=project_id,
                    name=name,
                    environment=env,
                    enabled=pair.desired,
                )

    def reconcile(
        self,
        client: UnleashServer,
        instance: UnleashInstanceV1,
        project_id: str,
        dry_run: bool,
        current_state: Sequence[FeatureToggle],
        desired_state: Iterable[FeatureToggleUnleashV1],
    ) -> None:
        """Reconcile the feature toggles."""
        self._reconcile_feature_toggles(
            client=client,
            instance=instance,
            project_id=project_id,
            dry_run=dry_run,
            current_state=current_state,
            desired_state=desired_state,
        )
        self._reconcile_states(
            client=client,
            instance=instance,
            project_id=project_id,
            dry_run=dry_run,
            current_state=current_state,
            desired_state=desired_state,
            available_environments=client.environments(project_id),
        )

    def run(self, dry_run: bool) -> None:
        gql_api = gql.get_api()
        instances = self.get_unleash_instances(
            gql_api.query, instance=self.params.instance
        )

        for instance in instances:
            assert instance.admin_token  # make mypy happy
            with UnleashServer(
                host=instance.url,
                auth=TokenAuth(self.secret_reader.read_secret(instance.admin_token)),
            ) as client:
                try:
                    project_pairs = self.validate_unleash_projects(
                        current_projects=self.fetch_current_state(client),
                        desired_projects=instance.projects or [],
                    )
                except ValueError:
                    logging.error(f"[{instance.name}] Missing projects!")
                    raise

                for pair in project_pairs:
                    self.reconcile(
                        client=client,
                        instance=instance,
                        project_id=pair.current.pk,
                        dry_run=dry_run,
                        current_state=pair.current.feature_toggles,
                        desired_state=pair.desired.feature_toggles or [],
                    )
