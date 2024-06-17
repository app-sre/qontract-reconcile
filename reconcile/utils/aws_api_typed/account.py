from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_account import AccountClient
else:
    AccountClient = object


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
