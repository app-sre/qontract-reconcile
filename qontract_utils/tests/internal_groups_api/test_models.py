import pytest
from qontract_utils.internal_groups_api.models import Entity, EntityType, Group

USER_1 = Entity(id="user-1", type=EntityType.USER)
GROUP = Group(
    name="group",
    description="group description",
    contact_list="email@example.org",
    owners=[USER_1],
    display_name="group display name",
    notes="group notes",
    members=[USER_1],
)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (USER_1, Entity(id="user-1", type=EntityType.USER), True),
        (USER_1, Entity(id="user-2", type=EntityType.USER), False),
    ],
)
def test_entity_eq(a: Entity, b: Entity, *, expected: bool) -> None:
    assert (a == b) is expected


def test_group_eq_same() -> None:
    assert GROUP.model_copy() == GROUP


def test_group_eq_different_description() -> None:
    other = Group(
        name="group",
        description="other",
        contact_list="email@example.org",
        owners=[USER_1],
        display_name="group display name",
        members=[USER_1],
    )
    assert other != GROUP
