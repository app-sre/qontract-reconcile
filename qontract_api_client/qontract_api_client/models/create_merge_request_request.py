from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.merge_request_file_operation import MergeRequestFileOperation
    from ..models.secret import Secret


T = TypeVar("T", bound="CreateMergeRequestRequest")


@_attrs_define
class CreateMergeRequestRequest:
    """Request to create a merge request in a VCS repository.

    Attributes:
        file_operations (list[MergeRequestFileOperation]): File operations to include in the MR
        repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
        source_branch (str): Source branch name
        title (str): Merge request title
        token (Secret): Reference to a secret stored in a secret manager.
        auto_merge (bool | Unset): Whether to enable auto-merge Default: False.
        description (str | Unset): Merge request description Default: ''.
        labels (list[str] | Unset): Labels to apply to the MR
        target_branch (str | Unset): Target branch name Default: 'master'.
    """

    file_operations: list[MergeRequestFileOperation]
    repo_url: str
    source_branch: str
    title: str
    token: Secret
    auto_merge: bool | Unset = False
    description: str | Unset = ""
    labels: list[str] | Unset = UNSET
    target_branch: str | Unset = "master"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        file_operations = []
        for file_operations_item_data in self.file_operations:
            file_operations_item = file_operations_item_data.to_dict()
            file_operations.append(file_operations_item)

        repo_url = self.repo_url

        source_branch = self.source_branch

        title = self.title

        token = self.token.to_dict()

        auto_merge = self.auto_merge

        description = self.description

        labels: list[str] | Unset = UNSET
        if not isinstance(self.labels, Unset):
            labels = self.labels

        target_branch = self.target_branch

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "file_operations": file_operations,
            "repo_url": repo_url,
            "source_branch": source_branch,
            "title": title,
            "token": token,
        })
        if auto_merge is not UNSET:
            field_dict["auto_merge"] = auto_merge
        if description is not UNSET:
            field_dict["description"] = description
        if labels is not UNSET:
            field_dict["labels"] = labels
        if target_branch is not UNSET:
            field_dict["target_branch"] = target_branch

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.merge_request_file_operation import MergeRequestFileOperation
        from ..models.secret import Secret

        d = dict(src_dict)
        file_operations = []
        _file_operations = d.pop("file_operations")
        for file_operations_item_data in _file_operations:
            file_operations_item = MergeRequestFileOperation.from_dict(
                file_operations_item_data
            )

            file_operations.append(file_operations_item)

        repo_url = d.pop("repo_url")

        source_branch = d.pop("source_branch")

        title = d.pop("title")

        token = Secret.from_dict(d.pop("token"))

        auto_merge = d.pop("auto_merge", UNSET)

        description = d.pop("description", UNSET)

        labels = cast(list[str], d.pop("labels", UNSET))

        target_branch = d.pop("target_branch", UNSET)

        create_merge_request_request = cls(
            file_operations=file_operations,
            repo_url=repo_url,
            source_branch=source_branch,
            title=title,
            token=token,
            auto_merge=auto_merge,
            description=description,
            labels=labels,
            target_branch=target_branch,
        )

        create_merge_request_request.additional_properties = d
        return create_merge_request_request

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
