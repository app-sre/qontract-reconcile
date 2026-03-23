from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="GithubOwnerActionAddOwner")


@_attrs_define
class GithubOwnerActionAddOwner:
    """Action: Add a user as an org admin (owner).

    Note: Owner removal is intentionally NOT supported. The integration only
    adds owners and never removes them, preserving the behavior of the original
    github-owners reconcile integration. This is a deliberate safety decision —
    removing org admins is a high-impact operation that requires explicit manual
    review rather than automated removal.

        Attributes:
            org_name (str): GitHub organization name
            username (str): GitHub username to add as org admin
            action_type (Literal['add_owner'] | Unset):  Default: 'add_owner'.
    """

    org_name: str
    username: str
    action_type: Literal["add_owner"] | Unset = "add_owner"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        org_name = self.org_name

        username = self.username

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "org_name": org_name,
            "username": username,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        org_name = d.pop("org_name")

        username = d.pop("username")

        action_type = cast(Literal["add_owner"] | Unset, d.pop("action_type", UNSET))
        if action_type != "add_owner" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'add_owner', got '{action_type}'"
            )

        github_owner_action_add_owner = cls(
            org_name=org_name,
            username=username,
            action_type=action_type,
        )

        github_owner_action_add_owner.additional_properties = d
        return github_owner_action_add_owner

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
