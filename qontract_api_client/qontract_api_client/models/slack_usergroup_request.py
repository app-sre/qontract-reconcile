from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.user_source_git_owners import UserSourceGitOwners
    from ..models.user_source_org_usernames import UserSourceOrgUsernames
    from ..models.user_source_pager_duty import UserSourcePagerDuty


T = TypeVar("T", bound="SlackUsergroupRequest")


@_attrs_define
class SlackUsergroupRequest:
    """A single Slack usergroup with its handle and configuration.

    Attributes:
        handle (str): Usergroup handle/name (unique identifier)
        description (str | Unset): Usergroup description Default: ''.
        user_sources (list[UserSourceGitOwners | UserSourceOrgUsernames | UserSourcePagerDuty] | Unset): List of user
            sources for this usergroup
        channels (list[str] | Unset): List of channel names (e.g., #general, team-channel)
    """

    handle: str
    description: str | Unset = ""
    user_sources: (
        list[UserSourceGitOwners | UserSourceOrgUsernames | UserSourcePagerDuty] | Unset
    ) = UNSET
    channels: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.user_source_git_owners import UserSourceGitOwners
        from ..models.user_source_org_usernames import UserSourceOrgUsernames

        handle = self.handle

        description = self.description

        user_sources: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.user_sources, Unset):
            user_sources = []
            for user_sources_item_data in self.user_sources:
                user_sources_item: dict[str, Any]
                if isinstance(user_sources_item_data, UserSourceOrgUsernames):
                    user_sources_item = user_sources_item_data.to_dict()
                elif isinstance(user_sources_item_data, UserSourceGitOwners):
                    user_sources_item = user_sources_item_data.to_dict()
                else:
                    user_sources_item = user_sources_item_data.to_dict()

                user_sources.append(user_sources_item)

        channels: list[str] | Unset = UNSET
        if not isinstance(self.channels, Unset):
            channels = self.channels

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "handle": handle,
        })
        if description is not UNSET:
            field_dict["description"] = description
        if user_sources is not UNSET:
            field_dict["user_sources"] = user_sources
        if channels is not UNSET:
            field_dict["channels"] = channels

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.user_source_git_owners import UserSourceGitOwners
        from ..models.user_source_org_usernames import UserSourceOrgUsernames
        from ..models.user_source_pager_duty import UserSourcePagerDuty

        d = dict(src_dict)
        handle = d.pop("handle")

        description = d.pop("description", UNSET)

        _user_sources = d.pop("user_sources", UNSET)
        user_sources: (
            list[UserSourceGitOwners | UserSourceOrgUsernames | UserSourcePagerDuty]
            | Unset
        ) = UNSET
        if _user_sources is not UNSET:
            user_sources = []
            for user_sources_item_data in _user_sources:

                def _parse_user_sources_item(
                    data: object,
                ) -> UserSourceGitOwners | UserSourceOrgUsernames | UserSourcePagerDuty:
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        user_sources_item_type_0 = UserSourceOrgUsernames.from_dict(
                            data
                        )

                        return user_sources_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        user_sources_item_type_1 = UserSourceGitOwners.from_dict(data)

                        return user_sources_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    user_sources_item_type_2 = UserSourcePagerDuty.from_dict(data)

                    return user_sources_item_type_2

                user_sources_item = _parse_user_sources_item(user_sources_item_data)

                user_sources.append(user_sources_item)

        channels = cast(list[str], d.pop("channels", UNSET))

        slack_usergroup_request = cls(
            handle=handle,
            description=description,
            user_sources=user_sources,
            channels=channels,
        )

        slack_usergroup_request.additional_properties = d
        return slack_usergroup_request

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
