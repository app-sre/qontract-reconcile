from typing import Callable

from reconcile.templating.rendering import FullRenderer, TemplateData


def test_full_rendering(template_from_fixture: Callable) -> None:
    template = template_from_fixture("full.yaml")

    r = FullRenderer(template, TemplateData(variables={"bar": "bar"}, current=None))

    assert r.get_output() == "foo: bar"
    assert r.get_target_path() == "/bar/foo.yml"
