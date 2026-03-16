from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.gi_project import GIProject
    from ..models.glitchtip_team import GlitchtipTeam
    from ..models.glitchtip_user import GlitchtipUser


T = TypeVar("T", bound="GIOrganization")


@_attrs_define
class GIOrganization:
    """Desired state for a single Glitchtip organization.

    Attributes:
        name (str): Organization name
        projects (list[GIProject] | Unset): Desired projects in this organization
        teams (list[GlitchtipTeam] | Unset): Desired teams in this organization
        users (list[GlitchtipUser] | Unset): Desired members of this organization
    """

    name: str
    projects: list[GIProject] | Unset = UNSET
    teams: list[GlitchtipTeam] | Unset = UNSET
    users: list[GlitchtipUser] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        projects: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.projects, Unset):
            projects = []
            for projects_item_data in self.projects:
                projects_item = projects_item_data.to_dict()
                projects.append(projects_item)

        teams: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.teams, Unset):
            teams = []
            for teams_item_data in self.teams:
                teams_item = teams_item_data.to_dict()
                teams.append(teams_item)

        users: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.users, Unset):
            users = []
            for users_item_data in self.users:
                users_item = users_item_data.to_dict()
                users.append(users_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
        })
        if projects is not UNSET:
            field_dict["projects"] = projects
        if teams is not UNSET:
            field_dict["teams"] = teams
        if users is not UNSET:
            field_dict["users"] = users

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.gi_project import GIProject
        from ..models.glitchtip_team import GlitchtipTeam
        from ..models.glitchtip_user import GlitchtipUser

        d = dict(src_dict)
        name = d.pop("name")

        _projects = d.pop("projects", UNSET)
        projects: list[GIProject] | Unset = UNSET
        if _projects is not UNSET:
            projects = []
            for projects_item_data in _projects:
                projects_item = GIProject.from_dict(projects_item_data)

                projects.append(projects_item)

        _teams = d.pop("teams", UNSET)
        teams: list[GlitchtipTeam] | Unset = UNSET
        if _teams is not UNSET:
            teams = []
            for teams_item_data in _teams:
                teams_item = GlitchtipTeam.from_dict(teams_item_data)

                teams.append(teams_item)

        _users = d.pop("users", UNSET)
        users: list[GlitchtipUser] | Unset = UNSET
        if _users is not UNSET:
            users = []
            for users_item_data in _users:
                users_item = GlitchtipUser.from_dict(users_item_data)

                users.append(users_item)

        gi_organization = cls(
            name=name,
            projects=projects,
            teams=teams,
            users=users,
        )

        gi_organization.additional_properties = d
        return gi_organization

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
