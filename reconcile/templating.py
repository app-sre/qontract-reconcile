from pprint import pprint
from typing import Optional, Callable
from jinja2.sandbox import SandboxedEnvironment
from jsonpath_ng.ext import parser

from reconcile.gql_definitions.templating.template_config import \
    TemplatingConfigurationV1, query
from reconcile.utils import gql
from reconcile.utils.runtime.integration import QontractReconcileIntegration

QONTRACT_INTEGRATION = "templating"


def get_templating_configuration(
    query_func: Optional[Callable] = None,
) -> list[TemplatingConfigurationV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).templating_configuration_v1 or []


def get_template_query_data(parent_query: str) -> dict:
    api = gql.get_api()
    api.validate_schemas = False
    return api.query(parent_query)


class TemplatingIntegration(QontractReconcileIntegration):
    def run(self, dry_run: bool) -> None:
        tc = get_templating_configuration()[0]
        template = tc.templates[0].template
        target_path = tc.templates[0].target_path
        env = SandboxedEnvironment()

        result = get_template_query_data(
            tc.parent_objects[0].parent_query.query)

        results = parser.parse(tc.parent_objects[0].parent_query.selector).find(result)
        for match in results:
            cluster = match.value

        render_vars = {
            "parent": cluster,
            "variables": tc.variables
        }
        rendered_template = env.from_string(template).render(**render_vars)
        rendered_target_path = env.from_string(target_path).render(**render_vars)

        print(rendered_template)

        print(rendered_target_path)




    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION
