from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_account import AccountClient
else:
    AccountClient = object

from pydantic import BaseModel


class OptStatus(StrEnum):
    """Optional status enum."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ENABLED_BY_DEFAULT = "ENABLED_BY_DEFAULT"


class Region(BaseModel):
    name: str
    status: OptStatus


class AWSApiAccount:
    def __init__(self, client: AccountClient) -> None:
        self.client = client

    def set_security_contact(
        self, name: str, title: str, email: str, phone_number: str
    ) -> None:
        """Set the security contact for the account."""
        self.client.put_alternate_contact(
            AlternateContactType="SECURITY",
            EmailAddress=email,
            Name=name,
            Title=title,
            PhoneNumber=phone_number,
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

    def enable_region(self, region: str) -> None:
        """Enable a region in the account."""
        self.client.enable_region(RegionName=region)

    def disable_region(self, region: str) -> None:
        """Disable a region in the account."""
        self.client.disable_region(RegionName=region)
