from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="MergeRequestFileOperation")


@_attrs_define
class MergeRequestFileOperation:
    """A file operation within a merge request.

    Set ``content`` to ``None`` to delete the file.

        Attributes:
            commit_message (str): Commit message for this file change
            content (None | str): File content (None = delete the file)
            path (str): File path in the repository
    """

    commit_message: str
    content: None | str
    path: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        commit_message = self.commit_message

        content: None | str
        content = self.content

        path = self.path

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "commit_message": commit_message,
            "content": content,
            "path": path,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        commit_message = d.pop("commit_message")

        def _parse_content(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        content = _parse_content(d.pop("content"))

        path = d.pop("path")

        merge_request_file_operation = cls(
            commit_message=commit_message,
            content=content,
            path=path,
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
