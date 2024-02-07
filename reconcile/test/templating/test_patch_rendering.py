from typing import Callable

import pytest

from reconcile.templating.rendering import PatchRenderer, TemplateData


@pytest.mark.parametrize(
    "fixture_file",
    [
        "patch_ref_simple.yaml",
        "patch_ref_updated.yaml",
        "patch_ref_overwrite.yaml",
        "patch_ref_overwrite_nested.yaml",
    ],
)
def test_patch_ref_update(
    get_fixture: Callable,
    fixture_file: str,
) -> None:
    template, current, expected = get_fixture(fixture_file).values()

    r = PatchRenderer(
        template, TemplateData(variables={"bar": "bar", "foo": "foo"}, current=current)
    )

    assert r.get_output().strip() == expected.strip()
