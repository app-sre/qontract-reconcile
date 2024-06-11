from enum import StrEnum

import requests
from pydantic import BaseModel, Field

from reconcile.utils.rest_api_base import ApiBase, BearerTokenAuth


class FeatureToggleType(StrEnum):
    experiment = "experiment"
    kill_switch = "kill-switch"
    release = "release"
    operational = "operational"
    permission = "permission"


class Environment(BaseModel):
    name: str
    enabled: bool

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Environment):
            return self.name == other.name
        return self.name == other


class FeatureToggle(BaseModel):
    name: str
    type: FeatureToggleType = FeatureToggleType.release
    description: str | None = None
    impression_data: bool = Field(False, alias="impressionData")
    environments: list[Environment]

    class Config:
        allow_population_by_field_name = True

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FeatureToggle):
            return self.name == other.name
        return self.name == other


class Project(BaseModel):
    pk: str = Field(alias="id")
    name: str
    feature_toggles: list[FeatureToggle] = []

    class Config:
        allow_population_by_field_name = True


class TokenAuth(BearerTokenAuth):
    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = self.token
        return r


class UnleashServer(ApiBase):
    """Unleash server API client."""

    def projects(self, include_feature_toggles: bool = False) -> list[Project]:
        """List all projects."""
        projects = []
        for project_data in self._list("/api/admin/projects", attribute="projects"):
            project = Project(**project_data)
            if include_feature_toggles:
                project.feature_toggles = self.feature_toggles(project.pk)
            projects.append(project)
        return projects

    def feature_toggles(self, project_id: str) -> list[FeatureToggle]:
        """List all feature toggles for a project."""
        return [
            FeatureToggle(**i)
            for i in self._list(
                f"/api/admin/projects/{project_id}/features", attribute="features"
            )
        ]

    def environments(self, project_id: str) -> list[Environment]:
        """Gets the environments that are available for this project. An environment is available for a project if enabled in the project configuration."""
        return [
            Environment(**i)
            for i in self._list(
                f"/api/admin/environments/project/{project_id}",
                attribute="environments",
            )
        ]

    def create_feature_toggle(
        self,
        project_id: str,
        name: str,
        description: str,
        type: FeatureToggleType,
        impression_data: bool,
    ) -> None:
        """Create a feature toggle."""
        self._post(
            f"/api/admin/projects/{project_id}/features",
            data={
                "name": name,
                "description": description,
                "type": type.value,
                "impressionData": impression_data,
            },
        )

    def update_feature_toggle(
        self,
        project_id: str,
        name: str,
        description: str,
        type: FeatureToggleType,
        impression_data: bool,
    ) -> None:
        """Create a feature toggle."""
        self._put(
            f"/api/admin/projects/{project_id}/features/{name}",
            data={
                "description": description,
                "type": type.value,
                "impressionData": impression_data,
            },
        )

    def delete_feature_toggle(self, project_id: str, name: str) -> None:
        """Delete a feature toggle."""
        # First archive the feature toggle
        self._delete(f"/api/admin/projects/{project_id}/features/{name}")
        # Then delete it
        self._post(
            f"/api/admin/projects/{project_id}/delete",
            data={"features": [name]},
        )

    def set_feature_toggle_state(
        self, project_id: str, name: str, environment: str, enabled: bool
    ) -> None:
        """Set the state of a feature toggle."""
        base_url = f"/api/admin/projects/{project_id}/features/{name}/environments/{environment}"
        if enabled:
            self._post(f"{base_url}/on")
        else:
            self._post(f"{base_url}/off")
