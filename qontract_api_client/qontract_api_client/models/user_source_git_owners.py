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

T = TypeVar("T", bound="UserSourceGitOwners")


@_attrs_define
class UserSourceGitOwners:
    """
    Attributes:
        git_url (str):
        provider (Literal['git_owners'] | Unset):  Default: 'git_owners'.
    """

    git_url: str
    provider: Literal["git_owners"] | Unset = "git_owners"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        git_url = self.git_url

        provider = self.provider

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "git_url": git_url,
        })
        if provider is not UNSET:
            field_dict["provider"] = provider

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        git_url = d.pop("git_url")

        provider = cast(Literal["git_owners"] | Unset, d.pop("provider", UNSET))
        if provider != "git_owners" and not isinstance(provider, Unset):
            raise ValueError(
                f"provider must match const 'git_owners', got '{provider}'"
            )

        user_source_git_owners = cls(
            git_url=git_url,
            provider=provider,
        )

        user_source_git_owners.additional_properties = d
        return user_source_git_owners

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
