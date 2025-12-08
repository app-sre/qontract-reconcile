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

T = TypeVar("T", bound="UserSourceOrgUsernames")


@_attrs_define
class UserSourceOrgUsernames:
    """
    Attributes:
        org_usernames (list[str]):
        provider (Literal['org_usernames'] | Unset):  Default: 'org_usernames'.
    """

    org_usernames: list[str]
    provider: Literal["org_usernames"] | Unset = "org_usernames"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        org_usernames = self.org_usernames

        provider = self.provider

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "org_usernames": org_usernames,
        })
        if provider is not UNSET:
            field_dict["provider"] = provider

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        org_usernames = cast(list[str], d.pop("org_usernames"))

        provider = cast(Literal["org_usernames"] | Unset, d.pop("provider", UNSET))
        if provider != "org_usernames" and not isinstance(provider, Unset):
            raise ValueError(
                f"provider must match const 'org_usernames', got '{provider}'"
            )

        user_source_org_usernames = cls(
            org_usernames=org_usernames,
            provider=provider,
        )

        user_source_org_usernames.additional_properties = d
        return user_source_org_usernames

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
