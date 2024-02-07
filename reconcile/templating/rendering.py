from abc import ABC, abstractmethod
from typing import Any, Optional

from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel
from ruamel import yaml

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.utils.jsonpath import parse_jsonpath


class Renderer(ABC):
    template: TemplateV1
    data: "TemplateData"

    def __init__(self, template: TemplateV1, data: "TemplateData"):
        self.template = template
        self.data = data
        self.jinja_env = SandboxedEnvironment()

    def _get_variables(self) -> dict[str, Any]:
        return self.data.variables

    def _get_current(self) -> dict[str, Any]:
        return self.data.current or {}

    def _jinja2_render_kwargs(self) -> dict[str, Any]:
        return {**self._get_variables(), "current": self._get_current()}

    def _render_template(self, template: str) -> str:
        return self.jinja_env.from_string(template).render(
            **self._jinja2_render_kwargs()
        )

    @abstractmethod
    def get_output(self) -> str:
        pass

    def get_target_path(self) -> str:
        return self._render_template(self.template.target_path)

    def should_render(self) -> bool:
        return bool(self._render_template(self.template.condition or "True"))


class FullRenderer(Renderer):
    def get_output(self) -> str:
        return self._render_template(self.template.template)


class PatchRenderer(Renderer):
    def get_output(self) -> str:
        if self.template.patch is None:
            raise ValueError("PatchRenderer requires a patch")

        p = parse_jsonpath(self.template.patch.path)

        matched_values = [match for match in p.find(self._get_current())]

        if len(matched_values) != 1:
            raise ValueError(
                f"Expected exactly one match for {self.template.patch.path}, got {len(matched_values)}"
            )
        matched_value = matched_values[0].value

        data_to_add = yaml.safe_load(self._render_template(self.template.template))

        if isinstance(matched_value, list):
            if not self.template.patch.identifier:
                raise ValueError(
                    f"Expected identifier in patch for list at {self.template}"
                )
            dta_identifier = data_to_add.get(self.template.patch.identifier)
            if not dta_identifier:
                raise ValueError(
                    f"Expected identifier {self.template.patch.identifier} in data to add"
                )

            updated = False
            for data in matched_value:
                if data.get(self.template.patch.identifier) == dta_identifier:
                    data.update(data_to_add)
                    updated = True
                    continue

            if not updated:
                matched_value.append(data_to_add)
        else:
            matched_value.update(data_to_add)

        return yaml.dump(self.data.current, width=4096, Dumper=yaml.RoundTripDumper)


class TemplateData(BaseModel):
    variables: dict[str, Any]
    current: Optional[dict[str, Any]]


def create_renderer(template: TemplateV1, data: TemplateData) -> Renderer:
    if template.patch:
        return PatchRenderer(template=template, data=data)
    else:
        return FullRenderer(template=template, data=data)
