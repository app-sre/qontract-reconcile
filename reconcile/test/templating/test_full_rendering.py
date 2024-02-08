from collections.abc import Callable

from reconcile.templating.rendering import FullRenderer, TemplateData


def test_full_rendering(get_fixture: Callable) -> None:
    template, _, expected = get_fixture("full.yaml").values()

    r = FullRenderer(template, TemplateData(variables={"bar": "bar"}, current=None))

    assert r.render_output() == expected
    assert r.render_target_path() == "/bar/foo.yml"


def test_full_not_rendering(get_fixture: Callable) -> None:
    template, _, _ = get_fixture("not_rendering.yaml").values()

    r = FullRenderer(template, TemplateData(variables={"bar": "bar"}, current=None))
    assert not r.render_condition()
