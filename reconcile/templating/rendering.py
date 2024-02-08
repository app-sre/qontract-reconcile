from abc import ABC, abstractmethod
from typing import Any, Optional

from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel
from ruamel import yaml

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.utils.jsonpath import parse_jsonpath


class TemplateData(BaseModel):
    variables: dict[str, Any]
    current: Optional[dict[str, Any]]


class Renderer(ABC):
    def __init__(self, template: TemplateV1, data: TemplateData):
        self.template = template
        self.data = data
        self.jinja_env = SandboxedEnvironment()

    def _jinja2_render_kwargs(self) -> dict[str, Any]:
        return {**self.data.variables, "current": self.data.current}

    def _render_template(self, template: str) -> str:
        return self.jinja_env.from_string(template).render(
            **self._jinja2_render_kwargs()
        )

    @abstractmethod
    def render_output(self) -> str:
        """
        Implementation of a renderer is required and should return the entire rendered file as a string.
        """
        pass

    def render_target_path(self) -> str:
        return self._render_template(self.template.target_path)

    def render_condition(self) -> bool:
        return self._render_template(self.template.condition or "True") == "True"


class FullRenderer(Renderer):
    def render_output(self) -> str:
        """
        Take the variables from Template Data and render the template with it.

        This method returns the entire file as a string.
        """
        return self._render_template(self.template.template)


class PatchRenderer(Renderer):
    def render_output(self) -> str:
        """
        Takes the variables from Template Data and render the template with it.

        This method partially updates the current data with the rendered template.
        It checks the existence of the path in the current data and updates it if it exists.
        If the path is not a list, it will update the value with the rendered template.

        This method returns the entire file as a string.
        """
        if self.template.patch is None:  # here to satisfy mypy
            raise ValueError("PatchRenderer requires a patch")

        p = parse_jsonpath(self.template.patch.path)

        matched_values = [match.value for match in p.find(self.data.current)]

        if len(matched_values) != 1:
            raise ValueError(
                f"Expected exactly one match for {self.template.patch.path}, got {len(matched_values)}"
            )
        matched_value = matched_values[0]

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

            data = next(
                (
                    data
                    for data in matched_value
                    if data.get(self.template.patch.identifier) == dta_identifier
                ),
                None,
            )
            if data is None:
                matched_value.append(data_to_add)
            else:
                data.update(data_to_add)
        else:
            matched_value.update(data_to_add)

        return yaml.dump(self.data.current, width=4096, Dumper=yaml.RoundTripDumper)


def create_renderer(template: TemplateV1, data: TemplateData) -> Renderer:
    if template.patch:
        return PatchRenderer(template=template, data=data)
    return FullRenderer(template=template, data=data)
