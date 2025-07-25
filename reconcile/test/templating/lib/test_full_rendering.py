from collections.abc import Callable

import pytest

from reconcile.templating.lib.rendering import FullRenderer, TemplateData
from reconcile.utils.secret_reader import SecretReader


def test_full_rendering(get_fixture: Callable, secret_reader: SecretReader) -> None:
    template, _, expected = get_fixture("full.yaml").values()

    r = FullRenderer(
        template,
        TemplateData(variables={"bar": "bar"}, current=None),
        secret_reader=secret_reader,
    )

    assert r.render_condition()
    assert r.render_output() == expected
    assert r.render_target_path() == "/bar/foo.yml"


@pytest.mark.parametrize(
    "fixture_file",
    [
        "full_not_rendering.yaml",
        "full_not_overwrite.yaml",
    ],
)
def test_full_not_rendering(
    get_fixture: Callable,
    fixture_file: str,
    secret_reader: SecretReader,
) -> None:
    template, current, _ = get_fixture(fixture_file).values()

    r = FullRenderer(
        template,
        TemplateData(variables={"bar": "bar"}, current=current),
        secret_reader=secret_reader,
    )
    assert not r.render_condition()
