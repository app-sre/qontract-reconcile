from typing import Callable

from reconcile.templating.rendering import FullRenderer, TemplateData


def test_full_rendering(get_fixture: Callable) -> None:
    template, _, expected = get_fixture("full.yaml").values()

    r = FullRenderer(template, TemplateData(variables={"bar": "bar"}, current=None))

    assert r.get_output() == expected
    assert r.get_target_path() == "/bar/foo.yml"
