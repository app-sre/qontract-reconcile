from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="SlackUsergroupsTaskResponse")


@_attrs_define
class SlackUsergroupsTaskResponse:
    """Response model for POST /reconcile endpoint.

    Returned immediately when task is queued. Contains task_id and status_url
    for retrieving the result via GET request.

        Attributes:
            id (str): Task ID
            status_url (str): URL to retrieve task result (GET request)
            status (TaskStatus | Unset): Status for background tasks.

                Used across all async API endpoints to indicate task execution state.
    """

    id: str
    status_url: str
    status: TaskStatus | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        status_url = self.status_url

        status: str | Unset = UNSET
        if not isinstance(self.status, Unset):
            status = self.status.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "status_url": status_url,
        })
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        status_url = d.pop("status_url")

        _status = d.pop("status", UNSET)
        status: TaskStatus | Unset
        if isinstance(_status, Unset):
            status = UNSET
        else:
            status = TaskStatus(_status)

        slack_usergroups_task_response = cls(
            id=id,
            status_url=status_url,
            status=status,
        )

        slack_usergroups_task_response.additional_properties = d
        return slack_usergroups_task_response

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
