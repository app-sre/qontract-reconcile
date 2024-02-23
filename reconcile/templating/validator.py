import logging
from difflib import context_diff
from typing import Callable, Optional

from pydantic import BaseModel
from ruamel import yaml

from reconcile.gql_definitions.templating.templates import (
    TemplateTestV1,
    TemplateV1,
    query,
)
from reconcile.templating.rendering import Renderer, TemplateData, create_renderer
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretReaderBase

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
    @staticmethod
    def _create_renderer(
        template: TemplateV1,
        template_test: TemplateTestV1,
        secret_reader: Optional[SecretReaderBase] = None,
    ) -> Renderer:
        return create_renderer(
            template,
            TemplateData(
                variables=template_test.variables or {},
                current=yaml.load(
                    template_test.current or "", Loader=yaml.RoundTripLoader
                ),
            ),
            secret_reader=secret_reader,
        )

    @staticmethod
    def validate_template(
        template: TemplateV1,
        template_test: TemplateTestV1,
        secret_reader: Optional[SecretReaderBase] = None,
    ) -> list[TemplateDiff]:
        diffs: list[TemplateDiff] = []

        r = TemplateValidatorIntegration._create_renderer(
            template, template_test, secret_reader=secret_reader
        )

        # Check target path
        if template_test.expected_target_path:
            rendered_target_path = r.render_target_path().strip()
            if rendered_target_path != template_test.expected_target_path.strip():
                diffs.append(
                    TemplateDiff(
                        template=template.name,
                        test=template_test.name,
                        diff=f"Target path mismatch, got: {rendered_target_path}, expected: {template_test.expected_target_path}",
                    )
                )

        # Check condition
        should_render = r.render_condition()
        if (
            template_test.expected_to_render is not None
            and template_test.expected_to_render != should_render
        ):
            diffs.append(
                TemplateDiff(
                    template=template.name,
                    test=template_test.name,
                    diff=f"Condition mismatch, got: {should_render}, expected: {template_test.expected_to_render}",
                )
            )

        # Check template output
        if should_render:
            output = r.render_output()
            diff = list(
                context_diff(
                    output.splitlines(keepends=True),
                    template_test.expected_output.splitlines(keepends=True),
                )
            )
            if diff:
                diffs.append(
                    TemplateDiff(
                        template=template.name,
                        test=template_test.name,
                        diff="".join(diff),
                    )
                )

        return diffs

    def run(self, dry_run: bool) -> None:
        diffs: list[TemplateDiff] = []

        for template in get_templates():
            for test in template.template_test:
                logging.info(f"Running test {test.name} for template {template.name}")
                diffs.extend(self.validate_template(template, test, self.secret_reader))

        if diffs:
            for diff in diffs:
                logging.error(
                    f"template: {diff.template}, test: {diff.test}: {diff.diff}"
                )
            raise ValueError("Template validation failed")

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION
