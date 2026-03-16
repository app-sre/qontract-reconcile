from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_user import GlitchtipUser


T = TypeVar("T", bound="GlitchtipTeam")


@_attrs_define
class GlitchtipTeam:
    """Desired state for a single Glitchtip team.

    Attributes:
        name (str): Team name (slug will be derived)
        users (list[GlitchtipUser] | Unset): Desired members of this team
    """

    name: str
    users: list[GlitchtipUser] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

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
        if users is not UNSET:
            field_dict["users"] = users

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.glitchtip_user import GlitchtipUser

        d = dict(src_dict)
        name = d.pop("name")

        _users = d.pop("users", UNSET)
        users: list[GlitchtipUser] | Unset = UNSET
        if _users is not UNSET:
            users = []
            for users_item_data in _users:
                users_item = GlitchtipUser.from_dict(users_item_data)

                users.append(users_item)

        glitchtip_team = cls(
            name=name,
            users=users,
        )

        glitchtip_team.additional_properties = d
        return glitchtip_team

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
