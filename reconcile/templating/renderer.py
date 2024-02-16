import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Optional

from pydantic import BaseModel
from ruamel import yaml

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionV1,
    TemplateCollectionVariablesV1,
    TemplateV1,
    query,
)
from reconcile.templating.rendering import (
    TemplateData,
    create_renderer,
)
from reconcile.utils import gql
from reconcile.utils.gql import init_from_config
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "template-renderer"

APP_INTERFACE_PATH_SEPERATOR = "/"


def get_template_collections(
    query_func: Optional[Callable] = None,
) -> list[TemplateCollectionV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).template_collection_v1 or []


class TemplateOutput(BaseModel):
    path: str
    content: str


class FilePersistence(ABC):
    @abstractmethod
    def write(self, outputs: list[TemplateOutput]) -> None:
        pass

    @abstractmethod
    def read(self, path: str) -> str:
        pass


class LocalFilePersistence(FilePersistence):
    def __init__(self, app_interface_data_path: str) -> None:
        self.app_interface_data_path = app_interface_data_path

    def write(self, outputs: list[TemplateOutput]) -> None:
        for output in outputs:
            with open(
                f"{join_path(self.app_interface_data_path, output.path)}",
                "w",
                encoding="utf-8",
            ) as f:
                f.write(output.content)

    def read(self, path: str) -> str:
        with open(
            f"{join_path(self.app_interface_data_path, path)}", "r", encoding="utf-8"
        ) as f:
            return f.read()


def unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> dict:
    variables = {}
    if collection_variables.static:
        variables = collection_variables.static
    return variables


def unpack_dynamic_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> dict:
    variables: dict[str, Any] = {}
    if collection_variables.dynamic:
        gql_no_validation = init_from_config(validate_schemas=False)
        for dv in collection_variables.dynamic or []:
            variables[dv.name] = []
            result = gql_no_validation.query(dv.query)
            for key in result or {}:
                variables[dv.name].append(result[key])
    return variables


class TemplateRendererIntegrationParams(PydanticRunParams):
    app_interface_data_path: Optional[str]


def join_path(base: str, sub: str) -> str:
    # not using os.path.sep, since app-interface relies on unix paths
    if sub.startswith(APP_INTERFACE_PATH_SEPERATOR):
        return os.path.join(base, sub[1:])
    return os.path.join(base, sub)


class TemplateRendererIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateRendererIntegrationParams) -> None:
        super().__init__(params)

    @staticmethod
    def process_template(
        template: TemplateV1,
        variables: dict,
        persistence: FilePersistence,
    ) -> Optional[TemplateOutput]:
        r = create_renderer(
            template,
            TemplateData(
                variables=variables,
            ),
        )
        target_path = r.render_target_path()
        current_str: Optional[str] = None
        try:
            current_str = persistence.read(
                target_path,
            )
            y = yaml.YAML()

            r.data.current = y.load(current_str)
        except FileNotFoundError:
            if template.patch:
                raise ValueError(f"Can not patch non-existing file {target_path}")

        if r.render_condition():
            output = r.render_output()

            if current_str != output:
                print(f"diff in template {template.name} for target_path {target_path}")
                return TemplateOutput(
                    path=target_path,
                    content=output,
                )
        return None

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        outputs: list[TemplateOutput] = []
        persistence = LocalFilePersistence(self.params.app_interface_data_path)

        for c in get_template_collections():
            variables = {}
            if c.variables:
                variables.update(unpack_dynamic_variables(c.variables))
                variables.update(unpack_static_variables(c.variables))

            for template in c.templates:
                output = self.process_template(
                    template,
                    variables,
                    persistence,
                )
                if output:
                    outputs.append(output)

            if not dry_run:
                persistence.write(outputs)
