from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.ldap_direct_secret import LdapDirectSecret


T = TypeVar("T", bound="LdapUsersCheckRequest")


@_attrs_define
class LdapUsersCheckRequest:
    """Request to check which usernames exist in LDAP.

    Attributes:
        secret (LdapDirectSecret): VaultSecret reference for FreeIPA direct LDAP access.

            The referenced Vault path must contain bind_dn and bind_password fields.
            No plain credentials are transmitted via API -- only Vault path references.

            Attributes:
                server_url: LDAP server URL (e.g., "ldap://freeipa.example.com")
                base_dn: Base DN for LDAP searches (e.g., "dc=example,dc=com")
                (inherited) secret_manager_url, path, field, version: Vault secret ref
        usernames (list[str]): Usernames to check
    """

    secret: LdapDirectSecret
    usernames: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        secret = self.secret.to_dict()

        usernames = self.usernames

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "secret": secret,
            "usernames": usernames,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ldap_direct_secret import LdapDirectSecret

        d = dict(src_dict)
        secret = LdapDirectSecret.from_dict(d.pop("secret"))

        usernames = cast(list[str], d.pop("usernames"))

        ldap_users_check_request = cls(
            secret=secret,
            usernames=usernames,
        )

        ldap_users_check_request.additional_properties = d
        return ldap_users_check_request

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
