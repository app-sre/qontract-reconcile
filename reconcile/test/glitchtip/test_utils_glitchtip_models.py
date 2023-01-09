from collections.abc import Mapping
from typing import Union

import pytest

from reconcile.utils.glitchtip import (
    Organization,
    Project,
    Team,
)
from reconcile.utils.glitchtip.models import slugify


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Simple", "simple"),
        ("Test123", "test123"),
        ("Test 1 2 3", "test-1-2-3"),
        ("Test-1 2 3", "test-1-2-3"),
        ("Test-1_2 3", "test-1_2-3"),
    ],
)
@pytest.mark.parametrize("model", [Organization, Project, Team])
def test_model_slugs(
    model: Union[type[Organization], type[Project], type[Team]], name: str, slug: str
) -> None:
    assert model(name=name).slug == slug


@pytest.mark.parametrize(
    "team_kwargs",
    [
        pytest.param(
            {"name": "Test", "slug": "Test 1 2 3"}, marks=pytest.mark.xfail(strict=True)
        ),
        {"name": "Test 1 2 3"},
        {"slug": "test-1-2-3"},
    ],
)
def test_model_team(team_kwargs: Mapping[str, str]) -> None:
    slug = slugify("Test 1 2 3")
    team = Team(**team_kwargs)
    assert team.name == slug
    assert team.slug == slug
