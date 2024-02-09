from collections.abc import Callable
from typing import Optional

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
from reconcile.utils.runtime.integration import QontractReconcileIntegration

QONTRACT_INTEGRATION = "template-renderer"


def get_template_collections(
    query_func: Optional[Callable] = None,
) -> list[TemplateCollectionV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).template_collection_v1 or []


def write_output(target_path: str, output: str) -> None:
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(output)


class TemplateValidatorIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def unpack_variables(collection_variables: TemplateCollectionVariablesV1) -> dict:
        variables = {}
        if collection_variables.static:
            variables = collection_variables.static
        return variables

    def run(self, dry_run: bool) -> None:
        for c in get_template_collections():
            variables = {}
            if c.variables:
                variables = self.unpack_variables(c.variables)

            for template in c.templates:
                if template.patch:
                    raise NotImplementedError("Patch is not implemented yet")

                r = create_renderer(
                    template,
                    TemplateData(
                        variables=variables,
                    ),
                )

                if r.render_condition():
                    target_path = r.render_target_path()
                    output = r.render_output()
                    print(target_path)
                    print(output)

                    if not dry_run:
                        write_output(target_path, output)
