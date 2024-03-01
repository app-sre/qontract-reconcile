import logging
from abc import ABC, abstractmethod
from io import StringIO
from typing import Any, Optional, Protocol

from pydantic import BaseModel

from reconcile.utils.jinja2.utils import Jinja2TemplateError, process_jinja2_template
from reconcile.utils.jsonpath import parse_jsonpath
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.secret_reader import SecretReaderBase


class TemplateData(BaseModel):
    variables: dict[str, Any]
    current: Optional[dict[str, Any]]


class TemplatePatch(Protocol):
    path: str
    identifier: Optional[str]

    def dict(self) -> dict[str, str]: ...


class Template(Protocol):
    name: str
    condition: Optional[str]
    target_path: str
    template: str

    def dict(self) -> dict[str, str]: ...

    @property
    def patch(self) -> Optional[TemplatePatch]:
        pass


class Renderer(ABC):
    def __init__(
        self,
        template: Template,
        data: TemplateData,
        secret_reader: Optional[SecretReaderBase] = None,
    ):
        self.template = template
        self.data = data
        self.secret_reader = secret_reader
        self.ruamel_instance = create_ruamel_instance()

    def _jinja2_render_kwargs(self) -> dict[str, Any]:
        return {**self.data.variables, "current": self.data.current}

    def _render_template(self, template: str) -> str:
        try:
            return process_jinja2_template(
                body=template,
                vars=self._jinja2_render_kwargs(),
                secret_reader=self.secret_reader,
            )
        except Jinja2TemplateError as e:
            logging.error(f"Error rendering template {self.template.name}: {e}")
            raise e

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

        data_to_add = self.ruamel_instance.load(
            self._render_template(self.template.template)
        )

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

            index = next(
                (
                    index
                    for index, data in enumerate(matched_value)
                    if data.get(self.template.patch.identifier) == dta_identifier
                ),
                None,
            )
            if index is None:
                matched_value.append(data_to_add)
            else:
                matched_value[index] = data_to_add
        else:
            matched_value.update(data_to_add)

        with StringIO() as s:
            self.ruamel_instance.dump(self.data.current, s)
            return s.getvalue()


def create_renderer(
    template: Template,
    data: TemplateData,
    secret_reader: Optional[SecretReaderBase] = None,
) -> Renderer:
    if template.patch:
        return PatchRenderer(template=template, data=data, secret_reader=secret_reader)
    return FullRenderer(
        template=template,
        data=data,
        secret_reader=secret_reader,
    )
