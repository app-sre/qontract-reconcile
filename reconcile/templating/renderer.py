import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Optional

from ruamel import yaml

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionV1,
    TemplateCollectionVariablesV1,
    query,
)
from reconcile.templating.rendering import (
    TemplateData,
    create_renderer,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "template-renderer"

APP_INTERFACE_PATH_SEPERATOR="/"

def get_template_collections(
    query_func: Optional[Callable] = None,
) -> list[TemplateCollectionV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).template_collection_v1 or []


class FilePersistence(ABC):

    @abstractmethod
    def read(self):
        raise

    @abstractmethod
    def write(self):
        raise



def unpack_variables(collection_variables: TemplateCollectionVariablesV1) -> dict:
    variables = {}
    if collection_variables.static:
        variables = collection_variables.static
    return variables

class TemplateRendererIntegrationParams(PydanticRunParams):
    app_interface_path: Optional[str]


def join_path(base: str, sub: str) -> str:
    # not using os.path.sep, since app-interface relies on unix paths
    if sub.startswith(APP_INTERFACE_PATH_SEPERATOR):
        return os.path.join(base, sub[1:])
    return os.path.join(base, sub)

class TemplateRendererIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateRendererIntegrationParams) -> None:
        super().__init__(params)

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_current_content(self, target_path: str) -> Optional[dict]:
        if self.params.app_interface_path:
            with open(f"{join_path(self.params.app_interface_path, target_path)}", "r", encoding="utf-8") as f:
                return yaml.load(f.read(), Loader=yaml.RoundTripLoader)
        raise NotImplementedError("Can not work with remote files yet, please provide app_interface_path.")

    def write_output(self, target_path: str, output: str) -> None:
        if self.params.app_interface_path:
            print(f"write {join_path(self.params.app_interface_path, target_path)} with {output}")
        # with open(target_path, "w", encoding="utf-8") as f:
        #     f.write(output)

    def run(self, dry_run: bool) -> None:
        for c in get_template_collections():
            variables = {}
            if c.variables:
                variables = unpack_variables(c.variables)

            for template in c.templates:
                r = create_renderer(
                    template,
                    TemplateData(
                        variables=variables,
                    ),
                )
                target_path = r.render_target_path()
                try:
                    current = self.get_current_content(
                        target_path,
                    )
                    r.data.current = current
                except FileNotFoundError:
                    if template.patch:
                        raise ValueError(
                            f"Can not patch non-existing file {target_path}")

                if r.render_condition():
                    output = r.render_output()
                    if not dry_run:
                        self.write_output(target_path, output)
