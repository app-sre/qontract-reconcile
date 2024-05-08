import logging
from collections.abc import Callable, Iterable, Sequence
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
from reconcile.utils.differ import diff_any_iterables
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
    return (
        c.description == d.description
        and c.type.value == d.unleash.q_type
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

    def get_project_by_name(
        self, projects: Iterable[UnleashProjectV1], name: str
    ) -> UnleashProjectV1:
        for project in projects:
            if project.name.lower() == name.lower():
                return project
        raise ValueError(f"Project {name} not found")

    def validate_unleash_projects(
        self,
        instance_name: str,
        current_projects: Iterable[Project],
        desired_projects: Iterable[UnleashProjectV1],
    ) -> None:
        """Validate that all projects referenced in the desired state are actually exist."""
        current_project_names = {p.name.lower() for p in current_projects}
        desired_project_names = {p.name.lower() for p in desired_projects}
        if missing_projects := desired_project_names - current_project_names:
            for p in missing_projects:
                logging.error(f"[{instance_name}] Project '{p}' does not exist!")
            raise ValueError(f"Non-existing projects: {missing_projects}")

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
                )
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
                )
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
        # Manage the actual feature toggle states
        for desired_toggle in desired_state:
            if not desired_toggle.unleash.environments:
                continue

            try:
                current_toggle = current_state[current_state.index(desired_toggle.name)]
            except ValueError:
                # The feature toggle does not exist yet
                continue

            desired_envs = [
                Environment(name=name, enabled=enabled)
                for name, enabled in desired_toggle.unleash.environments.items()
            ]
            non_existing_envs = set(e.name for e in desired_envs) - set(
                e.name for e in available_environments
            )
            for non_existing_env in non_existing_envs:
                logging.error(
                    f"[{instance.name}/{project_id}/{desired_toggle.name}] Environment '{non_existing_env}' does not exist!"
                )
            if non_existing_envs:
                raise ValueError(
                    f"[{instance.name}/{project_id}/{desired_toggle.name}] Check the environments in the feature toggle!"
                )
            diff_envs = diff_any_iterables(
                current=current_toggle.environments,
                desired=desired_envs,
                current_key=lambda c: c.name,
                desired_key=lambda d: d.name,
                equal=lambda c, d: c.enabled == d.enabled,
            )
            # we only care about the states of all managed environments and ignore all other
            for env_change in diff_envs.change.values():
                logging.info(
                    f"[{instance.name}/{project_id}/{desired_toggle.name}] Setting {env_change.desired.name}={env_change.desired.enabled}"
                )
                if not dry_run:
                    client.set_feature_toggle_state(
                        project_id=project_id,
                        name=desired_toggle.name,
                        environment=env_change.desired.name,
                        enabled=env_change.desired.enabled,
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
                projects = self.fetch_current_state(client)
                self.validate_unleash_projects(
                    instance_name=instance.name,
                    current_projects=projects,
                    desired_projects=instance.projects or [],
                )
                for project in projects:
                    self.reconcile(
                        client=client,
                        instance=instance,
                        project_id=project.pk,
                        dry_run=dry_run,
                        current_state=project.feature_toggles,
                        desired_state=self.get_project_by_name(
                            instance.projects or [], project.name
                        ).feature_toggles
                        or [],
                    )
