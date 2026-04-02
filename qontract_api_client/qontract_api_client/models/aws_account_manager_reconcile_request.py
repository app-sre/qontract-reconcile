from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.aws_account_manager_reconcile_request_default_tags import (
        AWSAccountManagerReconcileRequestDefaultTags,
    )
    from ..models.aws_account_organization import AWSAccountOrganization
    from ..models.aws_quota import AWSQuota
    from ..models.aws_security_contact import AWSSecurityContact
    from ..models.secret import Secret


T = TypeVar("T", bound="AWSAccountManagerReconcileRequest")


@_attrs_define
class AWSAccountManagerReconcileRequest:
    """Request to reconcile a single AWS account.

    If ``organization`` is present, the account is treated as an organization
    account (payer credentials + role assumption). Otherwise it is a standalone
    account with direct credentials.

        Attributes:
            account_name (str): Account name
            automation_token (Secret): Reference to a secret stored in a secret manager.
            resources_default_region (str): Default AWS region
            security_contact (AWSSecurityContact): Security contact information for an AWS account.
            uid (str): AWS account ID
            alias (None | str | Unset): Desired account alias
            automation_role (None | str | Unset): Payer's manager role ARN (required for org accounts)
            default_tags (AWSAccountManagerReconcileRequestDefaultTags | Unset): Default tags for the account
            dry_run (bool | Unset): If True, only calculate actions without executing. Default: True.
            enterprise_support (bool | Unset): Whether enterprise support is required Default: False.
            organization (AWSAccountOrganization | None | Unset): Organization details (OU + tags). If set, account is org-
                managed.
            organization_account_role (str | Unset): Role to assume in org account Default: 'OrganizationAccountAccessRole'.
            payer_uid (None | str | Unset): Payer account UID (required for org accounts — role assumed on payer, not org
                account)
            quotas (list[AWSQuota] | Unset): Desired service quotas
            supported_deployment_regions (list[str] | Unset): Desired enabled regions
    """

    account_name: str
    automation_token: Secret
    resources_default_region: str
    security_contact: AWSSecurityContact
    uid: str
    alias: None | str | Unset = UNSET
    automation_role: None | str | Unset = UNSET
    default_tags: AWSAccountManagerReconcileRequestDefaultTags | Unset = UNSET
    dry_run: bool | Unset = True
    enterprise_support: bool | Unset = False
    organization: AWSAccountOrganization | None | Unset = UNSET
    organization_account_role: str | Unset = "OrganizationAccountAccessRole"
    payer_uid: None | str | Unset = UNSET
    quotas: list[AWSQuota] | Unset = UNSET
    supported_deployment_regions: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.aws_account_organization import AWSAccountOrganization

        account_name = self.account_name

        automation_token = self.automation_token.to_dict()

        resources_default_region = self.resources_default_region

        security_contact = self.security_contact.to_dict()

        uid = self.uid

        alias: None | str | Unset
        if isinstance(self.alias, Unset):
            alias = UNSET
        else:
            alias = self.alias

        automation_role: None | str | Unset
        if isinstance(self.automation_role, Unset):
            automation_role = UNSET
        else:
            automation_role = self.automation_role

        default_tags: dict[str, Any] | Unset = UNSET
        if not isinstance(self.default_tags, Unset):
            default_tags = self.default_tags.to_dict()

        dry_run = self.dry_run

        enterprise_support = self.enterprise_support

        organization: dict[str, Any] | None | Unset
        if isinstance(self.organization, Unset):
            organization = UNSET
        elif isinstance(self.organization, AWSAccountOrganization):
            organization = self.organization.to_dict()
        else:
            organization = self.organization

        organization_account_role = self.organization_account_role

        payer_uid: None | str | Unset
        if isinstance(self.payer_uid, Unset):
            payer_uid = UNSET
        else:
            payer_uid = self.payer_uid

        quotas: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.quotas, Unset):
            quotas = []
            for quotas_item_data in self.quotas:
                quotas_item = quotas_item_data.to_dict()
                quotas.append(quotas_item)

        supported_deployment_regions: list[str] | Unset = UNSET
        if not isinstance(self.supported_deployment_regions, Unset):
            supported_deployment_regions = self.supported_deployment_regions

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "automation_token": automation_token,
            "resources_default_region": resources_default_region,
            "security_contact": security_contact,
            "uid": uid,
        })
        if alias is not UNSET:
            field_dict["alias"] = alias
        if automation_role is not UNSET:
            field_dict["automation_role"] = automation_role
        if default_tags is not UNSET:
            field_dict["default_tags"] = default_tags
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if enterprise_support is not UNSET:
            field_dict["enterprise_support"] = enterprise_support
        if organization is not UNSET:
            field_dict["organization"] = organization
        if organization_account_role is not UNSET:
            field_dict["organization_account_role"] = organization_account_role
        if payer_uid is not UNSET:
            field_dict["payer_uid"] = payer_uid
        if quotas is not UNSET:
            field_dict["quotas"] = quotas
        if supported_deployment_regions is not UNSET:
            field_dict["supported_deployment_regions"] = supported_deployment_regions

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aws_account_manager_reconcile_request_default_tags import (
            AWSAccountManagerReconcileRequestDefaultTags,
        )
        from ..models.aws_account_organization import AWSAccountOrganization
        from ..models.aws_quota import AWSQuota
        from ..models.aws_security_contact import AWSSecurityContact
        from ..models.secret import Secret

        d = dict(src_dict)
        account_name = d.pop("account_name")

        automation_token = Secret.from_dict(d.pop("automation_token"))

        resources_default_region = d.pop("resources_default_region")

        security_contact = AWSSecurityContact.from_dict(d.pop("security_contact"))

        uid = d.pop("uid")

        def _parse_alias(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        alias = _parse_alias(d.pop("alias", UNSET))

        def _parse_automation_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        automation_role = _parse_automation_role(d.pop("automation_role", UNSET))

        _default_tags = d.pop("default_tags", UNSET)
        default_tags: AWSAccountManagerReconcileRequestDefaultTags | Unset
        if isinstance(_default_tags, Unset):
            default_tags = UNSET
        else:
            default_tags = AWSAccountManagerReconcileRequestDefaultTags.from_dict(
                _default_tags
            )

        dry_run = d.pop("dry_run", UNSET)

        enterprise_support = d.pop("enterprise_support", UNSET)

        def _parse_organization(data: object) -> AWSAccountOrganization | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                organization_type_0 = AWSAccountOrganization.from_dict(data)

                return organization_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AWSAccountOrganization | None | Unset, data)

        organization = _parse_organization(d.pop("organization", UNSET))

        organization_account_role = d.pop("organization_account_role", UNSET)

        def _parse_payer_uid(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        payer_uid = _parse_payer_uid(d.pop("payer_uid", UNSET))

        _quotas = d.pop("quotas", UNSET)
        quotas: list[AWSQuota] | Unset = UNSET
        if _quotas is not UNSET:
            quotas = []
            for quotas_item_data in _quotas:
                quotas_item = AWSQuota.from_dict(quotas_item_data)

                quotas.append(quotas_item)

        supported_deployment_regions = cast(
            list[str], d.pop("supported_deployment_regions", UNSET)
        )

        aws_account_manager_reconcile_request = cls(
            account_name=account_name,
            automation_token=automation_token,
            resources_default_region=resources_default_region,
            security_contact=security_contact,
            uid=uid,
            alias=alias,
            automation_role=automation_role,
            default_tags=default_tags,
            dry_run=dry_run,
            enterprise_support=enterprise_support,
            organization=organization,
            organization_account_role=organization_account_role,
            payer_uid=payer_uid,
            quotas=quotas,
            supported_deployment_regions=supported_deployment_regions,
        )

        aws_account_manager_reconcile_request.additional_properties = d
        return aws_account_manager_reconcile_request

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
