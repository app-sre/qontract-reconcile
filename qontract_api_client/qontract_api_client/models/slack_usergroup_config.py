from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.notification_add_user import NotificationAddUser
    from ..models.notification_remove_user import NotificationRemoveUser


T = TypeVar("T", bound="SlackUsergroupConfig")


@_attrs_define
class SlackUsergroupConfig:
    """Desired state configuration for a single Slack usergroup.

    Attributes:
        channels (list[str] | Unset): List of channel names (e.g., #general, team-channel)
        description (str | Unset): Usergroup description Default: ''.
        notifications (list[NotificationAddUser | NotificationRemoveUser] | Unset): Notification actions triggered on
            membership changes
        users (list[str] | Unset): List of user emails (e.g., user@example.com)
    """

    channels: list[str] | Unset = UNSET
    description: str | Unset = ""
    notifications: list[NotificationAddUser | NotificationRemoveUser] | Unset = UNSET
    users: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.notification_add_user import NotificationAddUser

        channels: list[str] | Unset = UNSET
        if not isinstance(self.channels, Unset):
            channels = self.channels

        description = self.description

        notifications: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.notifications, Unset):
            notifications = []
            for notifications_item_data in self.notifications:
                notifications_item: dict[str, Any]
                if isinstance(notifications_item_data, NotificationAddUser):
                    notifications_item = notifications_item_data.to_dict()
                else:
                    notifications_item = notifications_item_data.to_dict()

                notifications.append(notifications_item)

        users: list[str] | Unset = UNSET
        if not isinstance(self.users, Unset):
            users = self.users

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if channels is not UNSET:
            field_dict["channels"] = channels
        if description is not UNSET:
            field_dict["description"] = description
        if notifications is not UNSET:
            field_dict["notifications"] = notifications
        if users is not UNSET:
            field_dict["users"] = users

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.notification_add_user import NotificationAddUser
        from ..models.notification_remove_user import NotificationRemoveUser

        d = dict(src_dict)
        channels = cast(list[str], d.pop("channels", UNSET))

        description = d.pop("description", UNSET)

        _notifications = d.pop("notifications", UNSET)
        notifications: list[NotificationAddUser | NotificationRemoveUser] | Unset = (
            UNSET
        )
        if _notifications is not UNSET:
            notifications = []
            for notifications_item_data in _notifications:

                def _parse_notifications_item(
                    data: object,
                ) -> NotificationAddUser | NotificationRemoveUser:
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        notifications_item_type_0 = NotificationAddUser.from_dict(data)

                        return notifications_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    notifications_item_type_1 = NotificationRemoveUser.from_dict(data)

                    return notifications_item_type_1

                notifications_item = _parse_notifications_item(notifications_item_data)

                notifications.append(notifications_item)

        users = cast(list[str], d.pop("users", UNSET))

        slack_usergroup_config = cls(
            channels=channels,
            description=description,
            notifications=notifications,
            users=users,
        )

        slack_usergroup_config.additional_properties = d
        return slack_usergroup_config

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
