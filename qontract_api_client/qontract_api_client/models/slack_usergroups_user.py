from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="SlackUsergroupsUser")


@_attrs_define
class SlackUsergroupsUser:
    """
    Attributes:
        org_username (str):
        github_username (None | str):
        pagerduty_username (None | str):
        tag_on_merge_requests (bool | None):
    """

    org_username: str
    github_username: None | str
    pagerduty_username: None | str
    tag_on_merge_requests: bool | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        org_username = self.org_username

        github_username: None | str
        github_username = self.github_username

        pagerduty_username: None | str
        pagerduty_username = self.pagerduty_username

        tag_on_merge_requests: bool | None
        tag_on_merge_requests = self.tag_on_merge_requests

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "org_username": org_username,
            "github_username": github_username,
            "pagerduty_username": pagerduty_username,
            "tag_on_merge_requests": tag_on_merge_requests,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        org_username = d.pop("org_username")

        def _parse_github_username(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        github_username = _parse_github_username(d.pop("github_username"))

        def _parse_pagerduty_username(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        pagerduty_username = _parse_pagerduty_username(d.pop("pagerduty_username"))

        def _parse_tag_on_merge_requests(data: object) -> bool | None:
            if data is None:
                return data
            return cast(bool | None, data)

        tag_on_merge_requests = _parse_tag_on_merge_requests(
            d.pop("tag_on_merge_requests")
        )

        slack_usergroups_user = cls(
            org_username=org_username,
            github_username=github_username,
            pagerduty_username=pagerduty_username,
            tag_on_merge_requests=tag_on_merge_requests,
        )

        slack_usergroups_user.additional_properties = d
        return slack_usergroups_user

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
