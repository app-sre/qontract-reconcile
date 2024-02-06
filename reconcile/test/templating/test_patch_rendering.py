from typing import Callable

from reconcile.templating.rendering import PatchRenderer, TemplateData


def test_patch_ref_simple(
    template_from_fixture: Callable, file_from_fixture: Callable
) -> None:
    template = template_from_fixture("patch_ref_simple.yaml")
    current = file_from_fixture("patch_ref_simple_current.yaml")

    r = PatchRenderer(template, TemplateData(variables={"bar": "bar"}, current=current))

    assert (
        r.get_output()
        == """resourceTemplates:
- name: saas
  targets:
  - namespace:
      $ref: existing.yaml
    version:
      foo: bar
  - namespace:
      $ref: additional.yaml
    version:
      foo: bar
"""
    )
