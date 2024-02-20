from collections.abc import Callable

from reconcile.templating.rendering import FullRenderer, TemplateData
from reconcile.utils.secret_reader import SecretReader


def test_full_rendering(get_fixture: Callable, secret_reader: SecretReader) -> None:
    template, _, expected = get_fixture("full.yaml").values()

    r = FullRenderer(
        template,
        TemplateData(variables={"bar": "bar"}, current=None),
        secret_reader=secret_reader,
    )

    assert r.render_output() == expected
    assert r.render_target_path() == "/bar/foo.yml"


def test_full_not_rendering(get_fixture: Callable, secret_reader: SecretReader) -> None:
    template, _, _ = get_fixture("not_rendering.yaml").values()

    r = FullRenderer(
        template,
        TemplateData(variables={"bar": "bar"}, current=None),
        secret_reader=secret_reader,
    )
    assert not r.render_condition()
