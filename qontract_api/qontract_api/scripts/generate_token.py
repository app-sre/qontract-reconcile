"""Generate JWT tokens for qontract-api authentication."""

# ruff: noqa: T201 - CLI output

import argparse
from datetime import timedelta

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


def main() -> None:
    """Generate JWT token."""
    parser = argparse.ArgumentParser(
        description="Generate JWT token for qontract-api authentication"
    )
    parser.add_argument(
        "--subject",
        required=True,
        help="Token subject (e.g., 'admin', 'service-account-name')",
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        default=30,
        help="Token expiration in days (default: 30)",
    )

    args = parser.parse_args()

    token_data = TokenData(sub=args.subject)
    expires_delta = timedelta(days=args.expires_days)
    token = create_access_token(data=token_data, expires_delta=expires_delta)

    print(f"Subject: {args.subject}")
    print(f"Expires: {args.expires_days} days")
    print(f"Token: {token}")


if __name__ == "__main__":
    main()
