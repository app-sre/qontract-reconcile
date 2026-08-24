"""Tests for qontract_utils.quay_api models."""

from qontract_utils.quay_api.models import (
    RobotAccount,
    RobotAccountPermission,
    RobotAccountRepository,
)


def test_robot_account_defaults() -> None:
    robot = RobotAccount(name="ci-bot")
    assert robot.name == "ci-bot"
    assert robot.description is None
    assert robot.teams == []
    assert robot.repositories == []


def test_robot_account_frozen() -> None:
    robot = RobotAccount(name="ci-bot", description="CI")
    assert robot.model_config.get("frozen") is True


def test_robot_account_permission_from_api_payload() -> None:
    perm = RobotAccountPermission.model_validate(
        {"repository": {"name": "repo1"}, "role": "read"}
    )
    assert perm.repository.name == "repo1"
    assert perm.role == "read"


def test_robot_account_repository() -> None:
    repo = RobotAccountRepository(name="images")
    assert repo.name == "images"
