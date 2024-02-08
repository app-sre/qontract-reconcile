import logging
from difflib import context_diff
from typing import Callable, Optional

from pydantic import BaseModel
from ruamel import yaml

from reconcile.gql_definitions.templating.templates import TemplateV1, query
from reconcile.templating.rendering import TemplateData, create_renderer
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    QontractReconcileIntegration,
    RunParamsTypeVar,
)

QONTRACT_INTEGRATION = "template-validator"


def get_templates(
    query_func: Optional[Callable] = None,
) -> list[TemplateV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).template_v1 or []


class TemplateDiff(BaseModel):
    template: str
    test: str
    diff: str


class TemplateValidatorIntegration(QontractReconcileIntegration):
    def __init__(self, params: RunParamsTypeVar) -> None:
        super().__init__(params)
        self.diffs: list[TemplateDiff] = []

    def diff_result(
        self, template_name: str, test_name: str, output: str, expected: str
    ) -> None:
        diff = list(
            context_diff(
                output.splitlines(keepends=True), expected.splitlines(keepends=True)
            )
        )
        if diff:
            self.diffs.append(
                TemplateDiff(template=template_name, test=test_name, diff="".join(diff))
            )

    def run(self, dry_run: bool) -> None:
        for template in get_templates():
            for test in template.template_test:
                logging.info(f"Running test {test.name} for template {template.name}")

                r = create_renderer(
                    template,
                    TemplateData(
                        variables=test.variables or {},
                        current=yaml.load(
                            test.current or "", Loader=yaml.RoundTripLoader
                        ),
                    ),
                )
                if test.expected_target_path:
                    self.diff_result(
                        template.name,
                        test.name,
                        r.render_target_path().strip(),
                        test.expected_target_path.strip(),
                    )
                should_render = r.render_condition()
                if (
                    test.expected_to_render is not None
                    and test.expected_to_render != should_render
                ):
                    self.diffs.append(
                        TemplateDiff(
                            template=template.name,
                            test=test.name,
                            diff=f"Condition mismatch, got: {should_render}, expected: {test.expected_to_render}",
                        )
                    )
                if should_render:
                    self.diff_result(
                        template.name,
                        test.name,
                        r.render_output().strip(),
                        test.expected_output.strip(),
                    )

        if self.diffs:
            for diff in self.diffs:
                logging.error(
                    f"template: {diff.template}, test: {diff.test}: {diff.diff}"
                )
            raise ValueError("Template validation")

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION
