from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.file_action import FileAction
from ..types import UNSET, Unset

T = TypeVar("T", bound="MergeRequestFileOperation")


@_attrs_define
class MergeRequestFileOperation:
    """A file operation within a merge request.

    The ``action`` field specifies the operation: create, update, or delete.

        Attributes:
            action (FileAction): File operation type for merge request file operations.
            commit_message (str): Commit message for this file change
            path (str): File path in the repository
            content (None | str | Unset): File content (required for create/update, None for delete)
    """

    action: FileAction
    commit_message: str
    path: str
    content: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        action = self.action.value

        commit_message = self.commit_message

        path = self.path

        content: None | str | Unset
        if isinstance(self.content, Unset):
            content = UNSET
        else:
            content = self.content

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "action": action,
            "commit_message": commit_message,
            "path": path,
        })
        if content is not UNSET:
            field_dict["content"] = content

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        action = FileAction(d.pop("action"))

        commit_message = d.pop("commit_message")

        path = d.pop("path")

        def _parse_content(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content = _parse_content(d.pop("content", UNSET))

        merge_request_file_operation = cls(
            action=action,
            commit_message=commit_message,
            path=path,
            content=content,
        )

        merge_request_file_operation.additional_properties = d
        return merge_request_file_operation

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
