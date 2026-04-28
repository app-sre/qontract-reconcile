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

T = TypeVar("T", bound="FileSyncDelete")


@_attrs_define
class FileSyncDelete:
    """Delete a file from the repository.

    Attributes:
        commit_message (str): Commit message for this change
        path (str): File path in the repository
        action (Literal['delete'] | Unset):  Default: 'delete'.
    """

    commit_message: str
    path: str
    action: Literal["delete"] | Unset = "delete"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        commit_message = self.commit_message

        path = self.path

        action = self.action

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "commit_message": commit_message,
            "path": path,
        })
        if action is not UNSET:
            field_dict["action"] = action

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        commit_message = d.pop("commit_message")

        path = d.pop("path")

        action = cast(Literal["delete"] | Unset, d.pop("action", UNSET))
        if action != "delete" and not isinstance(action, Unset):
            raise ValueError(f"action must match const 'delete', got '{action}'")

        file_sync_delete = cls(
            commit_message=commit_message,
            path=path,
            action=action,
        )

        file_sync_delete.additional_properties = d
        return file_sync_delete

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
