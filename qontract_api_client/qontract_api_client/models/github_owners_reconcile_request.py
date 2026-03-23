from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.github_org_desired_state import GithubOrgDesiredState


T = TypeVar("T", bound="GithubOwnersReconcileRequest")


@_attrs_define
class GithubOwnersReconcileRequest:
    """Request model for github-owners reconciliation.

    POST requests always queue a background task and return immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

        Attributes:
            organizations (list[GithubOrgDesiredState]): List of GitHub organizations with their desired owner membership
            dry_run (bool | Unset): If True, only calculate actions without executing. Default: True (safety first!)
                Default: True.
    """

    organizations: list[GithubOrgDesiredState]
    dry_run: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        organizations = []
        for organizations_item_data in self.organizations:
            organizations_item = organizations_item_data.to_dict()
            organizations.append(organizations_item)

        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "organizations": organizations,
        })
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.github_org_desired_state import GithubOrgDesiredState

        d = dict(src_dict)
        organizations = []
        _organizations = d.pop("organizations")
        for organizations_item_data in _organizations:
            organizations_item = GithubOrgDesiredState.from_dict(
                organizations_item_data
            )

            organizations.append(organizations_item)

        dry_run = d.pop("dry_run", UNSET)

        github_owners_reconcile_request = cls(
            organizations=organizations,
            dry_run=dry_run,
        )

        github_owners_reconcile_request.additional_properties = d
        return github_owners_reconcile_request

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
