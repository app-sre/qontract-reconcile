import json
import logging
from difflib import context_diff
from typing import Callable, Optional

from pydantic import BaseModel
from ruamel import yaml
from validator import validate_bundle # type: ignore
from validator.bundle import load_bundle # type: ignore
from yamllint import linter  # type: ignore
from yamllint.config import YamlLintConfig  # type: ignore

from reconcile.gql_definitions.templating.templates import TemplateV1, query
from reconcile.templating.rendering import TemplateData, create_renderer
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    QontractReconcileIntegration,
    RunParamsTypeVar, PydanticRunParams,
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


class TemplateError(BaseModel):
    template: str
    error: str
    lineno: Optional[int] = None


def validate_template(bundle_file: str, template_name: str, target_path: str , yaml_to_validate: str) -> list[TemplateError]:
    with open(bundle_file) as b:
        bundle = load_bundle(b)

    bundle.data[target_path] = yaml.safe_load(yaml_to_validate)

    results = validate_bundle(bundle)
    errors = list(filter(lambda x: x["result"]["status"] == "ERROR", results))

    print(json.dumps(errors, indent=4) + "\n")

    return []

def lint_yaml(template_name: str, yaml_to_lint: str) -> list[TemplateError]:
    # Possibly move this path to the templating configuration schema in the future
    resource = gql.get_api().get_resource("/yamllint/yamllint.yml")
    config = YamlLintConfig(content=resource["content"])

    return [
        TemplateError(
            template=template_name, error=problem.message, lineno=problem.line
        )
        for problem in linter.run(yaml_to_lint, config, "")
    ]


class TemplateValidatorIntegrationParams(PydanticRunParams):
    bundle_file: Optional[str]


class TemplateValidatorIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateValidatorIntegrationParams) -> None:
        super().__init__(params)
        self.diffs: list[TemplateDiff] = []
        self.errors: list[TemplateError] = []

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
                logging.debug(f"Running test {test.name} for template {template.name}")

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
                    output = r.render_output()
                    self.diff_result(
                        template.name,
                        test.name,
                        output.strip(),
                        test.expected_output.strip(),
                    )

                    if self.params.bundle_file:
                        validate_template(self.params.bundle_file, template.name, "added-by-test.yml", output)

                    self.errors.extend(lint_yaml(template.name, output))

        if self.diffs or self.errors:
            for diff in self.diffs:
                logging.error(
                    f"template: {diff.template}, test: {diff.test}: {diff.diff}"
                )
            for err in self.errors:
                logging.error(
                    f"template: {err.template}, line: {err.lineno}, error: {err.error}"
                )
            raise ValueError("Template validation failed")

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION
