from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.file_sync_create import FileSyncCreate
    from ..models.file_sync_delete import FileSyncDelete
    from ..models.file_sync_update import FileSyncUpdate
    from ..models.secret import Secret


T = TypeVar("T", bound="FileSyncRequest")


@_attrs_define
class FileSyncRequest:
    """Request to reconcile file state in a VCS repository.

    Deduplicates by MR title and creates a merge request with the
    given file operations. Relies on the VCS provider for validation.

        Attributes:
            file_operations (list[FileSyncCreate | FileSyncDelete | FileSyncUpdate]): File operations to reconcile
            repo_url (str): Repository URL (e.g., https://gitlab.com/group/project)
            target_branch (str): Target branch name
            title (str): Merge request title (used for deduplication)
            token (Secret): Reference to a secret stored in a secret manager.
            auto_merge (bool | Unset): Whether to enable auto-merge Default: False.
            description (str | Unset): Merge request description Default: ''.
            labels (list[str] | Unset): Labels to apply to the MR
    """

    file_operations: list[FileSyncCreate | FileSyncDelete | FileSyncUpdate]
    repo_url: str
    target_branch: str
    title: str
    token: Secret
    auto_merge: bool | Unset = False
    description: str | Unset = ""
    labels: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.file_sync_create import FileSyncCreate
        from ..models.file_sync_update import FileSyncUpdate

        file_operations = []
        for file_operations_item_data in self.file_operations:
            file_operations_item: dict[str, Any]
            if isinstance(file_operations_item_data, FileSyncCreate):
                file_operations_item = file_operations_item_data.to_dict()
            elif isinstance(file_operations_item_data, FileSyncUpdate):
                file_operations_item = file_operations_item_data.to_dict()
            else:
                file_operations_item = file_operations_item_data.to_dict()

            file_operations.append(file_operations_item)

        repo_url = self.repo_url

        target_branch = self.target_branch

        title = self.title

        token = self.token.to_dict()

        auto_merge = self.auto_merge

        description = self.description

        labels: list[str] | Unset = UNSET
        if not isinstance(self.labels, Unset):
            labels = self.labels

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "file_operations": file_operations,
            "repo_url": repo_url,
            "target_branch": target_branch,
            "title": title,
            "token": token,
        })
        if auto_merge is not UNSET:
            field_dict["auto_merge"] = auto_merge
        if description is not UNSET:
            field_dict["description"] = description
        if labels is not UNSET:
            field_dict["labels"] = labels

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.file_sync_create import FileSyncCreate
        from ..models.file_sync_delete import FileSyncDelete
        from ..models.file_sync_update import FileSyncUpdate
        from ..models.secret import Secret

        d = dict(src_dict)
        file_operations = []
        _file_operations = d.pop("file_operations")
        for file_operations_item_data in _file_operations:

            def _parse_file_operations_item(
                data: object,
            ) -> FileSyncCreate | FileSyncDelete | FileSyncUpdate:
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    file_operations_item_type_0 = FileSyncCreate.from_dict(data)

                    return file_operations_item_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    file_operations_item_type_1 = FileSyncUpdate.from_dict(data)

                    return file_operations_item_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                file_operations_item_type_2 = FileSyncDelete.from_dict(data)

                return file_operations_item_type_2

            file_operations_item = _parse_file_operations_item(
                file_operations_item_data
            )

            file_operations.append(file_operations_item)

        repo_url = d.pop("repo_url")

        target_branch = d.pop("target_branch")

        title = d.pop("title")

        token = Secret.from_dict(d.pop("token"))

        auto_merge = d.pop("auto_merge", UNSET)

        description = d.pop("description", UNSET)

        labels = cast(list[str], d.pop("labels", UNSET))

        file_sync_request = cls(
            file_operations=file_operations,
            repo_url=repo_url,
            target_branch=target_branch,
            title=title,
            token=token,
            auto_merge=auto_merge,
            description=description,
            labels=labels,
        )

        file_sync_request.additional_properties = d
        return file_sync_request

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
