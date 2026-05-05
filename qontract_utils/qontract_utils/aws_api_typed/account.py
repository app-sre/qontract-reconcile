from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_account import AccountClient
    from mypy_boto3_account.type_defs import AlternateContactTypeDef


class OptStatus(StrEnum):
    """Optional status enum."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ENABLED_BY_DEFAULT = "ENABLED_BY_DEFAULT"


class Region(BaseModel):
    name: str
    status: OptStatus


log = logging.getLogger(__name__)


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiAccount:
    _hooks: Hooks

    def __init__(self, client: AccountClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="set_security_contact", service="account")
    )
    def set_security_contact(
        self, name: str, title: str, email: str, phone_number: str
    ) -> None:
        """Set the security contact for the account."""
        try:
            self.client.put_alternate_contact(
                AlternateContactType="SECURITY",
                EmailAddress=email,
                Name=name,
                Title=title,
                PhoneNumber=phone_number,
            )
        except self.client.exceptions.AccessDeniedException:
            # This exception is raised if the user does not have permission to perform this action.
            # Let's see if the current security contact is already set to the same values.
            current_contact = self.get_security_contact()
            if (
                not current_contact
                or current_contact["EmailAddress"] != email
                or current_contact["Name"] != name
                or current_contact["Title"] != title
                or current_contact["PhoneNumber"] != phone_number
            ):
                raise

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_security_contact", service="account")
    )
    def get_security_contact(self) -> AlternateContactTypeDef | None:
        """Get the security contact for the account."""
        try:
            return self.client.get_alternate_contact(AlternateContactType="SECURITY")[
                "AlternateContact"
            ]
        except self.client.exceptions.ResourceNotFoundException:
            log.warning("Security contact not set.")
            return None

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="list_regions", service="account")
    )
    def list_regions(self) -> list[Region]:
        """List all regions in the account."""
        regions = []
        paginator = self.client.get_paginator("list_regions")
        for page in paginator.paginate():
            for region in page["Regions"]:
                match region["RegionOptStatus"]:
                    case "DISABLED" | "DISABLING":
                        status = OptStatus.DISABLED
                    case "ENABLED" | "ENABLING":
                        status = OptStatus.ENABLED
                    case "ENABLED_BY_DEFAULT":
                        status = OptStatus.ENABLED_BY_DEFAULT
                    case _:
                        raise ValueError(f"Unknown status: {region['RegionOptStatus']}")
                regions.append(Region(name=region["RegionName"], status=status))
        return regions

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="enable_region", service="account")
    )
    def enable_region(self, region: str) -> None:
        """Enable a region in the account."""
        self.client.enable_region(RegionName=region)

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="disable_region", service="account")
    )
    def disable_region(self, region: str) -> None:
        """Disable a region in the account."""
        self.client.disable_region(RegionName=region)
