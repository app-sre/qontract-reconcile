import logging
from abc import ABC, abstractmethod
from functools import cached_property
from io import StringIO
from typing import Any, Protocol

from pydantic import BaseModel

from reconcile.utils.jinja2.utils import (
    Jinja2TemplateError,
    TemplateRenderOptions,
    process_jinja2_template,
)
from reconcile.utils.jsonpath import parse_jsonpath
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.secret_reader import SecretReaderBase


class TemplateData(BaseModel):
    variables: dict[str, Any]
    current: dict[str, Any] | None
    current_with_explicit_start: bool | None = False


class TemplatePatch(Protocol):
    path: str
    identifier: str | None

    def dict(self) -> dict[str, str]: ...


class Template(Protocol):
    name: str
    condition: str | None
    target_path: str
    template: str
    overwrite: bool | None

    def dict(self) -> dict[str, str]: ...

    @property
    def patch(self) -> TemplatePatch | None:
        pass


class Renderer(ABC):
    def __init__(
        self,
        template: Template,
        data: TemplateData,
        secret_reader: SecretReaderBase | None = None,
        template_render_options: TemplateRenderOptions | None = None,
    ):
        self.template = template
        self.data = data
        self.secret_reader = secret_reader
        self.ruamel_instance = create_ruamel_instance(explicit_start=True)
        self.template_render_options = template_render_options

    def _jinja2_render_kwargs(self) -> dict[str, Any]:
        return {**self.data.variables, "current": self.data.current}

    def _render_template(self, template: str) -> str:
        try:
            return process_jinja2_template(
                body=template,
                vars=self._jinja2_render_kwargs(),
                secret_reader=self.secret_reader,
                template_render_options=self.template_render_options,
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

    @abstractmethod
    def target_exist(self) -> bool:
        """
        if target (file or patch block) already exists.
        """
        pass

    def render_target_path(self) -> str:
        return self._render_template(self.template.target_path).strip()

    def render_condition(self) -> bool:
        if self._render_template(self.template.condition or "True") != "True":
            return False
        if self.template.overwrite:
            return True
        return not self.target_exist()


class FullRenderer(Renderer):
    def target_exist(self) -> bool:
        return self.data.current is not None

    def render_output(self) -> str:
        """
        Take the variables from Template Data and render the template with it.

        This method returns the entire file as a string.
        """
        return self._render_template(self.template.template)


class PatchRenderer(Renderer):
    def target_exist(self) -> bool:
        if isinstance(self._matched_value, list):
            dta_identifier = self._get_identifier(self._data_to_add)
            return self._find_index(self._matched_value, dta_identifier) is not None
        return True

    def render_output(self) -> str:
        """
        Takes the variables from Template Data and render the template with it.

        This method partially updates the current data with the rendered template.
        It checks the existence of the path in the current data and updates it if it exists.
        If the path is not a list, it will update the value with the rendered template.

        This method returns the entire file as a string.
        """
        if isinstance(self._matched_value, list):
            dta_identifier = self._get_identifier(self._data_to_add)
            if not dta_identifier:
                assert self.template.patch is not None  # mypy
                raise ValueError(
                    f"Expected identifier {self.template.patch.identifier} in data to add"
                )
            if (
                index := self._find_index(self._matched_value, dta_identifier)
            ) is not None:
                self._matched_value[index] = self._data_to_add
            else:
                self._matched_value.append(self._data_to_add)
        else:
            self._matched_value.update(self._data_to_add)

        with StringIO() as s:
            self.ruamel_instance.dump(self.data.current, s)
            return s.getvalue()

    @cached_property
    def _matched_value(self) -> Any:
        assert self.template.patch is not None  # mypy
        p = parse_jsonpath(self._render_template(self.template.patch.path))
        matched_values = [match.value for match in p.find(self.data.current)]
        if len(matched_values) != 1:
            raise ValueError(
                f"Expected exactly one match for {self.template.patch.path}, got {len(matched_values)}"
            )
        return matched_values[0]

    @cached_property
    def _data_to_add(self) -> Any:
        return self.ruamel_instance.load(self._render_template(self.template.template))

    def _get_identifier(self, data: dict[str, Any]) -> Any:
        assert self.template.patch is not None  # mypy
        if not self.template.patch.identifier:
            raise ValueError(
                f"Expected identifier in patch for list at {self.template}"
            )
        if self.template.patch.identifier.startswith(
            "$"
        ) and not self.template.patch.identifier.startswith("$ref"):
            # jsonpath and list of strings support
            if matches := [
                match.value
                for match in parse_jsonpath(self.template.patch.identifier).find(data)
            ]:
                return matches[0]
            return None
        return data.get(self.template.patch.identifier)

    def _find_index(
        self,
        matched_value: list,
        dta_identifier: Any,
    ) -> int | None:
        for index, data in enumerate(matched_value):
            if self._get_identifier(data) == dta_identifier:
                return index
        return None


def create_renderer(
    template: Template,
    data: TemplateData,
    secret_reader: SecretReaderBase | None = None,
    template_render_options: TemplateRenderOptions | None = None,
) -> Renderer:
    if template.patch:
        return PatchRenderer(
            template=template,
            data=data,
            secret_reader=secret_reader,
            template_render_options=template_render_options,
        )
    return FullRenderer(
        template=template,
        data=data,
        secret_reader=secret_reader,
        template_render_options=template_render_options,
    )
