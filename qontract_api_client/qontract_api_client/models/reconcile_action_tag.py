from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.reconcile_action_tag_tags import ReconcileActionTagTags


T = TypeVar("T", bound="ReconcileActionTag")


@_attrs_define
class ReconcileActionTag:
    """Action: account tags updated.

    Attributes:
        account_name (str): Account name
        tags (ReconcileActionTagTags): Applied tags
        action_type (Literal['tag'] | Unset):  Default: 'tag'.
    """

    account_name: str
    tags: ReconcileActionTagTags
    action_type: Literal["tag"] | Unset = "tag"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        tags = self.tags.to_dict()

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "tags": tags,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.reconcile_action_tag_tags import ReconcileActionTagTags

        d = dict(src_dict)
        account_name = d.pop("account_name")

        tags = ReconcileActionTagTags.from_dict(d.pop("tags"))

        action_type = cast(Literal["tag"] | Unset, d.pop("action_type", UNSET))
        if action_type != "tag" and not isinstance(action_type, Unset):
            raise ValueError(f"action_type must match const 'tag', got '{action_type}'")

        reconcile_action_tag = cls(
            account_name=account_name,
            tags=tags,
            action_type=action_type,
        )

        reconcile_action_tag.additional_properties = d
        return reconcile_action_tag

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
