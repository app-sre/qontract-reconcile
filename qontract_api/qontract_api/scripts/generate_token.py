"""Temporary script to generate JWT tokens for qontract-api authentication.

This script will be replace by a proper management CLI in the future.
"""

# ruff: noqa: PLC0415 - local import in main

import argparse
import os
from datetime import timedelta

from rich import print as rich_print
from rich.panel import Panel
from rich.table import Table


def setup() -> None:
    """Setup environment for qontract-api."""
    os.environ.setdefault(
        "QAPI_SECRETS__DEFAULT_PROVIDER_URL", "http://not-used-in-this-script"
    )
    os.environ.setdefault("QAPI_SECRETS__PROVIDERS", "[]")
    if "QAPI_JWT_SECRET_KEY" not in os.environ:
        rich_print(
            Panel(
                "[red]QAPI_JWT_SECRET_KEY environment variable not set, using the default development key instead!!!",
                title="Warning",
            )
        )


def main() -> None:
    """Generate JWT token."""
    # import locally to have all environment setup done before importing qontract_api modules
    from qontract_api.auth import create_access_token
    from qontract_api.models import TokenData

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
        required=True,
        help="Token expiration in days",
    )

    args = parser.parse_args()

    token_data = TokenData(sub=args.subject)
    expires_delta = timedelta(days=args.expires_days)
    token = create_access_token(data=token_data, expires_delta=expires_delta)

    grid = Table(title="JWT", show_header=False, show_lines=True)
    grid.add_row("Subject", args.subject)
    grid.add_row("Expires", f"{args.expires_days} days")
    grid.add_row("Token", f"[green]{token}")
    rich_print(grid)


if __name__ == "__main__":
    setup()
    main()
