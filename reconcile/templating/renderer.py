import logging
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
from reconcile.utils.ruamel import create_ruamel_instance
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
    def read(self, path: str) -> Optional[str]:
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

    def read(self, path: str) -> Optional[str]:
        try:
            with open(
                f"{join_path(self.app_interface_data_path, path)}",
                "r",
                encoding="utf-8",
            ) as f:
                return f.read()
        except FileNotFoundError:
            logging.debug(f"File not found: {path}, need to create it")
        return None


def unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> dict:
    return collection_variables.static or {}


def unpack_dynamic_variables(
    collection_variables: TemplateCollectionVariablesV1, gql: gql.GqlApi
) -> dict[str, dict[str, Any]]:
    if not collection_variables.dynamic:
        return {}

    return {
        dv.name: gql.query(dv.query) or {} for dv in collection_variables.dynamic or []
    }


class TemplateRendererIntegrationParams(PydanticRunParams):
    app_interface_data_path: Optional[str]


def join_path(base: str, sub: str) -> str:
    return os.path.join(base, sub.lstrip(APP_INTERFACE_PATH_SEPERATOR))


class TemplateRendererIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateRendererIntegrationParams) -> None:
        super().__init__(params)

    def process_template(
        self,
        template: TemplateV1,
        variables: dict,
        persistence: FilePersistence,
        ruaml_instance: yaml.YAML,
    ) -> Optional[TemplateOutput]:
        r = create_renderer(
            template,
            TemplateData(
                variables=variables,
            ),
            secret_reader=self.secret_reader,
        )
        target_path = r.render_target_path()

        current_str = persistence.read(
            target_path,
        )
        if current_str is None and template.patch:
            raise ValueError(f"Can not patch non-existing file {target_path}")

        if current_str:
            r.data.current = ruaml_instance.load(current_str)

        if r.render_condition():
            output = r.render_output()

            if current_str != output:
                logging.info(
                    f"diff for template {template.name} in target path {target_path}"
                )
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
        gql_no_validation = init_from_config(validate_schemas=False)
        persistence = LocalFilePersistence(self.params.app_interface_data_path)

        ruaml_instance = create_ruamel_instance()

        for c in get_template_collections():
            if c.variables:
                variables = {
                    "dynamic": unpack_dynamic_variables(c.variables, gql_no_validation),
                    "static": unpack_static_variables(c.variables),
                }

            for template in c.templates:
                output = self.process_template(
                    template,
                    variables,
                    persistence,
                    ruaml_instance,
                )
                if output:
                    outputs.append(output)

            if not dry_run:
                persistence.write(outputs)
