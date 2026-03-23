from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.secret import Secret


T = TypeVar("T", bound="GithubOrgDesiredState")


@_attrs_define
class GithubOrgDesiredState:
    """Desired owner state for a single GitHub organization.

    Attributes:
        org_name: GitHub organization name
        token: Vault secret reference for the org's GitHub API token
        base_url: GitHub API base URL (override for GitHub Enterprise)
        owners: Desired set of lowercase GitHub usernames that should be org admins

        Attributes:
            org_name (str): GitHub organization name
            owners (list[str]): Desired set of GitHub usernames that should be org admins
            token (Secret): Reference to a secret stored in a secret manager.
            base_url (str | Unset): GitHub API base URL (override for GitHub Enterprise) Default: 'https://api.github.com'.
    """

    org_name: str
    owners: list[str]
    token: Secret
    base_url: str | Unset = "https://api.github.com"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        org_name = self.org_name

        owners = self.owners

        token = self.token.to_dict()

        base_url = self.base_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "org_name": org_name,
            "owners": owners,
            "token": token,
        })
        if base_url is not UNSET:
            field_dict["base_url"] = base_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.secret import Secret

        d = dict(src_dict)
        org_name = d.pop("org_name")

        owners = cast(list[str], d.pop("owners"))

        token = Secret.from_dict(d.pop("token"))

        base_url = d.pop("base_url", UNSET)

        github_org_desired_state = cls(
            org_name=org_name,
            owners=owners,
            token=token,
            base_url=base_url,
        )

        github_org_desired_state.additional_properties = d
        return github_org_desired_state

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
