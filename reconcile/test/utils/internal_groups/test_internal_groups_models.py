import json

import pytest

from reconcile.utils.internal_groups.models import (
    Entity,
    EntityType,
    Group,
)

USER_1 = Entity(id="user-1", type=EntityType.USER)
USER_2 = Entity(id="user-2", type=EntityType.USER)
SERVICE_ACCOUNT_1 = Entity(id="user-1", type=EntityType.SERVICE_ACCOUNT)
SERVICE_ACCOUNT_2 = Entity(id="service-account-2", type=EntityType.SERVICE_ACCOUNT)

GROUP = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)
GROUP_DESC_CHANGED = Group(
    name="group",
    description="foobar description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)
GROUP_APPR_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="ticket",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)
GROUP_CONTACT_LIST_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="foobar@lalaland.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)
GROUP_OWNERS_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1, SERVICE_ACCOUNT_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)
GROUP_DISPLAY_NAME_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group nothing to see here",
    notes="group notes",
    members=[USER_1],
)
GROUP_NOTES_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="the greatest group ever",
    members=[USER_1],
)
GROUP_MEMBERS_CHANGED = Group(
    name="group",
    description="group description",
    member_approval_type="self-service",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1, USER_2],
)


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (USER_1, USER_1, True),
        (USER_1, USER_2, False),
        (USER_1, SERVICE_ACCOUNT_1, False),
        (USER_1, SERVICE_ACCOUNT_2, False),
    ],
)
def test_internal_groups_models_entity_eq(a: Entity, b: Entity, expected: bool) -> None:
    assert (a == b) is expected


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (GROUP, GROUP, True),
        (GROUP, GROUP_DESC_CHANGED, False),
        (GROUP, GROUP_APPR_CHANGED, False),
        (GROUP, GROUP_CONTACT_LIST_CHANGED, False),
        (GROUP, GROUP_OWNERS_CHANGED, False),
        (GROUP, GROUP_DISPLAY_NAME_CHANGED, False),
        (GROUP, GROUP_NOTES_CHANGED, False),
        (GROUP, GROUP_MEMBERS_CHANGED, False),
    ],
)
def test_internal_groups_models_group_eq(a: Group, b: Group, expected: bool) -> None:
    assert (a == b) is expected


def test_internal_groups_models_group_json() -> None:
    assert GROUP.json(by_alias=True, sort_keys=True) == json.dumps(
        {
            "name": "group",
            "description": "group description",
            "memberApprovalType": "self-service",
            "contactList": "email@example.org",
            "owners": [{"id": "user-1", "type": "user"}],
            "displayName": "group display name",
            "notes": "group notes",
            "members": [{"id": "user-1", "type": "user"}],
        },
        sort_keys=True,
    )
