from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.vcs_provider import VCSProvider
from ..types import UNSET, Unset

T = TypeVar("T", bound="RepoOwnersResponse")


@_attrs_define
class RepoOwnersResponse:
    """Response model for repository OWNERS file data.

    Attention: usernames are provider-specific (e.g., GitHub usernames).

        Attributes:
            provider (VCSProvider): VCS provider types.

                Extensible enum for supported VCS providers.
            approvers (list[str] | Unset): List of usernames who can approve changes
            reviewers (list[str] | Unset): List of usernames who can review changes
    """

    provider: VCSProvider
    approvers: list[str] | Unset = UNSET
    reviewers: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider.value

        approvers: list[str] | Unset = UNSET
        if not isinstance(self.approvers, Unset):
            approvers = self.approvers

        reviewers: list[str] | Unset = UNSET
        if not isinstance(self.reviewers, Unset):
            reviewers = self.reviewers

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "provider": provider,
        })
        if approvers is not UNSET:
            field_dict["approvers"] = approvers
        if reviewers is not UNSET:
            field_dict["reviewers"] = reviewers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        provider = VCSProvider(d.pop("provider"))

        approvers = cast(list[str], d.pop("approvers", UNSET))

        reviewers = cast(list[str], d.pop("reviewers", UNSET))

        repo_owners_response = cls(
            provider=provider,
            approvers=approvers,
            reviewers=reviewers,
        )

        repo_owners_response.additional_properties = d
        return repo_owners_response

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
