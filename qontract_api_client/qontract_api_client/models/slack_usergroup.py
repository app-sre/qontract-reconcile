from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.slack_usergroup_config import SlackUsergroupConfig


T = TypeVar("T", bound="SlackUsergroup")


@_attrs_define
class SlackUsergroup:
    """A single Slack usergroup with its handle and configuration.

    Attributes:
        config (SlackUsergroupConfig): Desired state configuration for a single Slack usergroup.
        handle (str): Usergroup handle/name (unique identifier)
    """

    config: SlackUsergroupConfig
    handle: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        handle = self.handle

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "config": config,
            "handle": handle,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.slack_usergroup_config import SlackUsergroupConfig

        d = dict(src_dict)
        config = SlackUsergroupConfig.from_dict(d.pop("config"))

        handle = d.pop("handle")

        slack_usergroup = cls(
            config=config,
            handle=handle,
        )

        slack_usergroup.additional_properties = d
        return slack_usergroup

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
