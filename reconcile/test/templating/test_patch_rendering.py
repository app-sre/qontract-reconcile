from collections.abc import Callable

import pytest

from reconcile.templating.rendering import PatchRenderer, TemplateData
from reconcile.utils.secret_reader import SecretReader


@pytest.mark.parametrize(
    "fixture_file",
    [
        "patch_simple.yaml",
        "patch_updated.yaml",
        "patch_overwrite.yaml",
        "patch_overwrite_nested.yaml",
    ],
)
def test_patch_ref_update(
    get_fixture: Callable,
    fixture_file: str,
    secret_reader: SecretReader,
) -> None:
    template, current, expected = get_fixture(fixture_file).values()

    r = PatchRenderer(
        template,
        TemplateData(variables={"bar": "bar", "foo": "foo"}, current=current),
        secret_reader=secret_reader,
    )

    assert r.render_output().strip() == expected.strip()


@pytest.mark.parametrize(
    "fixture_file",
    [
        "patch_wrong_identifier.yaml",
        "patch_missing_identifier.yaml",
    ],
)
def test_patch_raises(
    get_fixture: Callable,
    fixture_file: str,
    secret_reader: SecretReader,
) -> None:
    template, _, _ = get_fixture(fixture_file).values()

    with pytest.raises(ValueError):
        r = PatchRenderer(
            template,
            TemplateData(variables={"bar": "bar", "foo": "foo"}),
            secret_reader=secret_reader,
        )
        r.render_output()
