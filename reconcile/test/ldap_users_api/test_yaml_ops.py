"""Tests for YAML manipulation helpers."""

from reconcile.ldap_users_api.mr_builder import (
    remove_user_from_aws_accounts,
    remove_user_from_gabi,
    remove_user_from_schedule,
)

# Test data
GABI_YAML = """\
---
users:
- $ref: /users/alice.yml
- $ref: /users/bob.yml
"""

GABI_YAML_ALICE_REMOVED = """\
---
users:
- $ref: /users/bob.yml
"""

AWS_YAML = """\
---
resetPasswords:
- user:
    $ref: /users/alice.yml
  accountName: prod
- user:
    $ref: /users/bob.yml
  accountName: staging
"""

AWS_YAML_ALICE_REMOVED = """\
---
resetPasswords:
- user:
    $ref: /users/bob.yml
  accountName: staging
"""

SCHEDULE_YAML = """\
---
schedule:
- users:
  - $ref: /users/alice.yml
  - $ref: /users/bob.yml
- users:
  - $ref: /users/alice.yml
"""

SCHEDULE_YAML_ALICE_REMOVED = """\
---
schedule:
- users:
  - $ref: /users/bob.yml
- users: []
"""


def test_remove_user_from_gabi() -> None:
    """Test removing a user from GABI users list."""
    result = remove_user_from_gabi(GABI_YAML, "alice")
    assert result == GABI_YAML_ALICE_REMOVED


def test_remove_user_from_gabi_not_found() -> None:
    """Test removing a user that doesn't exist from GABI - should return original."""
    result = remove_user_from_gabi(GABI_YAML, "charlie")
    assert result == GABI_YAML


def test_remove_user_from_aws_accounts() -> None:
    """Test removing a user from AWS resetPasswords list."""
    result = remove_user_from_aws_accounts(AWS_YAML, "alice")
    assert result == AWS_YAML_ALICE_REMOVED


def test_remove_user_from_aws_accounts_not_found() -> None:
    """Test removing a user that doesn't exist from AWS - should return original."""
    result = remove_user_from_aws_accounts(AWS_YAML, "charlie")
    assert result == AWS_YAML


def test_remove_user_from_schedule() -> None:
    """Test removing a user from all schedule entries."""
    result = remove_user_from_schedule(SCHEDULE_YAML, "alice")
    assert result == SCHEDULE_YAML_ALICE_REMOVED


def test_remove_user_from_schedule_not_found() -> None:
    """Test removing a user that doesn't exist from schedule - should return original."""
    result = remove_user_from_schedule(SCHEDULE_YAML, "charlie")
    assert result == SCHEDULE_YAML
