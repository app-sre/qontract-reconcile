from datetime import datetime as dt
from typing import Optional
from unittest.mock import (
    Mock,
    create_autospec,
)

import pytest
from pydantic import BaseModel

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils import pagerduty_api


class PagerDutyInstance(BaseModel):
    name: str
    token: VaultSecret


class User(BaseModel):
    org_username: str
    pagerduty_username: Optional[str]


class PagerDutyTarget(BaseModel):
    name: str
    instance: PagerDutyInstance
    schedule_id: Optional[str]
    escalation_policy_id: Optional[str]


@pytest.fixture
def user() -> User:
    return User(
        org_username="org",
        pagerduty_username="pagerduty",
    )


class PDUser(BaseModel):
    id: str
    email: str


@pytest.fixture()
def pypd_user(mocker: Mock):
    m = mocker.patch("pypd.User", autospec=True)
    m.find.return_value = [
        PDUser(id="user_id1", email="user1@foobar.com"),
        PDUser(id="user_id2", email="user2@foobar.com"),
    ]
    m.fetch.return_value = PDUser(id="user_id1", email="user1@foobar.com")
    return m


@pytest.fixture()
def pypd_schedule(mocker: Mock):
    m = mocker.patch("pypd.Schedule", autospec=True)
    m.fetch.return_value = {
        "final_schedule": {
            "rendered_schedule_entries": [
                {"user": {"id": "user_id1"}},
                {"user": {"id": "user_id2"}},
                {"user": {"id": "fooabr", "deleted_at": "lalala"}},
            ]
        }
    }
    return m


@pytest.fixture()
def pypd_escalation_policy(mocker: Mock):
    m = mocker.patch("pypd.EscalationPolicy", autospec=True)
    m.fetch.return_value = {
        "escalation_rules": [
            {
                "targets": [
                    {"type": "schedule_reference", "id": "id"},
                    {"type": "user_reference", "id": "id"},
                ],
                "escalation_delay_in_minutes": 5,
            }
        ]
    }
    return m


def test_get_pagerduty_map(secret_reader: Mock, vault_secret: VaultSecret) -> None:
    pager_duty_api_class = create_autospec(pagerduty_api.PagerDutyApi)
    pd_map = pagerduty_api.get_pagerduty_map(
        secret_reader=secret_reader,
        pagerduty_instances=[
            PagerDutyInstance(name="inst1", token=vault_secret),
            PagerDutyInstance(name="inst2", token=vault_secret),
        ],
        init_users=True,
        pager_duty_api_class=pager_duty_api_class,
    )
    assert len(pd_map.pd_apis) == 2
    assert "inst1" in pd_map.pd_apis
    assert "inst2" in pd_map.pd_apis
    assert isinstance(pd_map.get("inst1"), pagerduty_api.PagerDutyApi)
    with pytest.raises(KeyError):
        pd_map.get("doesn't-exist")


def test_get_pagerduty_username_org_username(user: User) -> None:
    assert pagerduty_api.get_pagerduty_name(user) == user.pagerduty_username
    user.pagerduty_username = None
    assert pagerduty_api.get_pagerduty_name(user) == user.org_username


def test_get_usernames_from_pagerduty(user: User, vault_secret: VaultSecret) -> None:
    pagerduties = [
        PagerDutyTarget(
            name="app-sre-pagerduty-primary-oncall",
            instance=PagerDutyInstance(name="redhat", token=vault_secret),
            schedule_id="PHS3079",
            escalation_policy_id=None,
        )
    ]
    mock_pagerduty_map = create_autospec(pagerduty_api.PagerDutyMap)
    mock_pagerduty_map.get.return_value.get_pagerduty_users.return_value = [
        "pagerduty+foobar",
        "nobody",
        "nobody+foobar",
    ]
    result = pagerduty_api.get_usernames_from_pagerduty(
        pagerduties=pagerduties,
        users=[user],
        usergroup="usergroup",
        pagerduty_map=mock_pagerduty_map,
        get_username_method=lambda u: u.org_username,
    )
    assert result == [user.org_username]


def test_get_usernames_from_pagerduty_bad_target(
    user: User, vault_secret: VaultSecret
) -> None:
    pagerduties = [
        PagerDutyTarget(
            name="app-sre-pagerduty-primary-oncall",
            instance=PagerDutyInstance(name="redhat", token=vault_secret),
            schedule_id=None,
            escalation_policy_id=None,
        )
    ]

    with pytest.raises(pagerduty_api.PagerDutyTargetException):
        pagerduty_api.get_usernames_from_pagerduty(
            pagerduties=pagerduties,
            users=[user],
            usergroup="usergroup",
            pagerduty_map=create_autospec(pagerduty_api.PagerDutyMap),
            get_username_method=lambda u: u.org_username,
        )


def test_pagerduty_api_init_init_users(pypd_user: Mock):
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=True)
    pypd_user.find.assert_called_once()
    assert len(pd_api.users) == 2


def test_pagerduty_api_init_not_init_users(pypd_user: Mock):
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    pypd_user.find.assert_not_called()
    assert len(pd_api.users) == 0


def test_pagerduty_api_init_users(pypd_user: Mock):
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    pd_api.init_users()
    pypd_user.find.assert_called_once()
    assert len(pd_api.users) == 2


def test_pagerduty_api_get_user_not_cached(pypd_user: Mock):
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    user = pd_api.get_user("user_id1")
    pypd_user.fetch.assert_called_once()
    assert len(pd_api.users) == 1
    assert user == "user1"


def test_pagerduty_api_get_user_cached(pypd_user: Mock):
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=True)
    user = pd_api.get_user("user_id1")
    pypd_user.fetch.assert_not_called()
    assert len(pd_api.users) == 2
    assert user == "user1"


def test_get_pagerduty_users_resource_type_schedule(mocker: Mock, pypd_user: Mock):
    mock_get_schedule_users = mocker.patch(
        "reconcile.utils.pagerduty_api.PagerDutyApi.get_schedule_users",
        return_value=["user1"],
    )
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    assert pd_api.get_pagerduty_users(
        resource_type="schedule", resource_id="foobar"
    ) == ["user1"]
    mock_get_schedule_users.assert_called_once()


def test_get_pagerduty_users_resource_type_escalation_policy(
    mocker: Mock, pypd_user: Mock
):
    mock_get_escalation_policy_users = mocker.patch(
        "reconcile.utils.pagerduty_api.PagerDutyApi.get_escalation_policy_users",
        return_value=["user2"],
    )
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    assert pd_api.get_pagerduty_users(
        resource_type="escalationPolicy", resource_id="foobar"
    ) == ["user2"]
    mock_get_escalation_policy_users.assert_called_once()


def test_get_schedule_users(mocker: Mock, pypd_schedule: Mock):
    mocker.patch(
        "reconcile.utils.pagerduty_api.PagerDutyApi.get_user",
        return_value="username",
    )
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    # 2 user in pypd_schedule
    assert pd_api.get_schedule_users(schedule_id="foo", now=dt.now()) == [
        "username",
        "username",
    ]


def test_get_escalation_policy_users(mocker: Mock, pypd_escalation_policy: Mock):
    mocker.patch(
        "reconcile.utils.pagerduty_api.PagerDutyApi.get_user",
        return_value="username_get_user",
    )
    mocker.patch(
        "reconcile.utils.pagerduty_api.PagerDutyApi.get_schedule_users",
        return_value=["username_get_schedule_users"],
    )
    pd_api = pagerduty_api.PagerDutyApi(token="secret", init_users=False)
    assert sorted(
        pd_api.get_escalation_policy_users(escalation_policy_id="foo", now=dt.now())
    ) == sorted(
        [
            "username_get_user",
            "username_get_schedule_users",
        ]
    )
