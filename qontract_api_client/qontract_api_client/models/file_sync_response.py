from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.file_sync_status import FileSyncStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="FileSyncResponse")


@_attrs_define
class FileSyncResponse:
    """Response from file sync reconciliation.

    Attributes:
        status (FileSyncStatus): Outcome of a file sync reconciliation.
        mr_url (None | str | Unset): URL of the created or existing merge request
    """

    status: FileSyncStatus
    mr_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value

        mr_url: None | str | Unset
        if isinstance(self.mr_url, Unset):
            mr_url = UNSET
        else:
            mr_url = self.mr_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "status": status,
        })
        if mr_url is not UNSET:
            field_dict["mr_url"] = mr_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        status = FileSyncStatus(d.pop("status"))

        def _parse_mr_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mr_url = _parse_mr_url(d.pop("mr_url", UNSET))

        file_sync_response = cls(
            status=status,
            mr_url=mr_url,
        )

        file_sync_response.additional_properties = d
        return file_sync_response

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
