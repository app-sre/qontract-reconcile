from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.gi_organization import GIOrganization
    from ..models.secret import Secret


T = TypeVar("T", bound="GIInstance")


@_attrs_define
class GIInstance:
    """Glitchtip instance configuration with desired state.

    Attributes:
        automation_user_email (Secret): Reference to a secret stored in a secret manager.
        console_url (str): Glitchtip instance base URL
        name (str): Instance name (unique identifier)
        token (Secret): Reference to a secret stored in a secret manager.
        max_retries (int | Unset): Max HTTP retries Default: 3.
        organizations (list[GIOrganization] | Unset): Desired organizations to reconcile
        read_timeout (int | Unset): HTTP read timeout in seconds Default: 30.
    """

    automation_user_email: Secret
    console_url: str
    name: str
    token: Secret
    max_retries: int | Unset = 3
    organizations: list[GIOrganization] | Unset = UNSET
    read_timeout: int | Unset = 30
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        automation_user_email = self.automation_user_email.to_dict()

        console_url = self.console_url

        name = self.name

        token = self.token.to_dict()

        max_retries = self.max_retries

        organizations: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.organizations, Unset):
            organizations = []
            for organizations_item_data in self.organizations:
                organizations_item = organizations_item_data.to_dict()
                organizations.append(organizations_item)

        read_timeout = self.read_timeout

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "automation_user_email": automation_user_email,
            "console_url": console_url,
            "name": name,
            "token": token,
        })
        if max_retries is not UNSET:
            field_dict["max_retries"] = max_retries
        if organizations is not UNSET:
            field_dict["organizations"] = organizations
        if read_timeout is not UNSET:
            field_dict["read_timeout"] = read_timeout

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.gi_organization import GIOrganization
        from ..models.secret import Secret

        d = dict(src_dict)
        automation_user_email = Secret.from_dict(d.pop("automation_user_email"))

        console_url = d.pop("console_url")

        name = d.pop("name")

        token = Secret.from_dict(d.pop("token"))

        max_retries = d.pop("max_retries", UNSET)

        _organizations = d.pop("organizations", UNSET)
        organizations: list[GIOrganization] | Unset = UNSET
        if _organizations is not UNSET:
            organizations = []
            for organizations_item_data in _organizations:
                organizations_item = GIOrganization.from_dict(organizations_item_data)

                organizations.append(organizations_item)

        read_timeout = d.pop("read_timeout", UNSET)

        gi_instance = cls(
            automation_user_email=automation_user_email,
            console_url=console_url,
            name=name,
            token=token,
            max_retries=max_retries,
            organizations=organizations,
            read_timeout=read_timeout,
        )

        gi_instance.additional_properties = d
        return gi_instance

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
