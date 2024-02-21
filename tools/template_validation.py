import json
import os.path
import sys
from pprint import pprint

import click
from ruamel import yaml
from validator.bundle import load_bundle
from validator.validator import validate_bundle
from yamllint import linter
from yamllint.config import YamlLintConfig

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.templating.validator import TemplateDiff, TemplateValidatorIntegration
from reconcile.utils.models import data_default_none
from reconcile.utils.ruamel import create_ruamel_instance


def validate_template(bundle_file: str, templates: dict[str, str]) -> list[dict]:
    with open(bundle_file, "r", encoding="utf-8") as b:
        bundle = load_bundle(b)

    for target_path, template_data in list(templates.items()):
        bundle.data[target_path] = yaml.safe_load(template_data)

    results = validate_bundle(bundle)
    return [
        result["result"] for result in results if result["result"]["status"] == "ERROR"
    ]


def load_clean_yaml(ai_path: str, path: str) -> dict:
    if not path.startswith("/data/"):
        to_load = os.path.join(ai_path, "data", path.lstrip("/"))
    else:
        to_load = os.path.join(ai_path, path.lstrip("/"))

    y = load_yaml(to_load)

    if "$schema" in y:
        del y["$schema"]
    return y


def load_yaml(to_load: str) -> dict:
    ruamel_instance = create_ruamel_instance()
    with open(to_load, "r", encoding="utf-8") as file:
        return ruamel_instance.load(file)


def print_validation_errors(errors: list[dict]) -> None:
    print("--------- VALIDATION ERRORS ---------")
    print(f"Found {len(errors)} errors during validation:")
    for error in errors:
        pprint(error)
    print("--------- END VALIDATION ERRORS ---------")


def print_lint_problems(lint_problems: list[linter.LintProblem]) -> None:
    print("--------- LINTING ISSUES ---------")
    print(f"Found {len(lint_problems)} lint problems:")
    for problem in lint_problems:
        print(f"Lint error in line: {problem.line}, {problem.desc}")
    print("--------- END LINTING ISSUES ---------")


def print_test_diffs(diffs: list[TemplateDiff]) -> None:
    print("--------- TEMPLATE TEST DIFF ---------")
    print("Template validation failed")
    for d in diffs:
        for line in d.diff.splitlines():
            if line:
                print(f"{line}")
    print("--------- END TEMPLATE TEST DIFF ---------")


@click.command()
@click.option(
    "--ai-path",
    help="Path to the bundle file",
    default=None,
    required=True,
)
@click.option(
    "--template-path",
    help="Path to the template file",
    default=None,
    required=True,
)
@click.option(
    "--run-validator",
    help="Should template validation invoke qontract-validator",
    default=False,
    is_flag=True,
)
def main(ai_path: str, template_path: str, run_validator: bool) -> None:
    okay = True
    templateRaw = load_clean_yaml(ai_path, template_path)

    tests = []
    for testRaw in templateRaw["templateTest"]:
        test_yaml = load_clean_yaml(ai_path, testRaw["$ref"])
        variables = json.dumps(test_yaml["variables"])
        test_yaml["variables"] = variables
        tests.append(test_yaml)

    templateRaw["templateTest"] = tests
    template: TemplateV1 = TemplateV1(**data_default_none(TemplateV1, templateRaw))

    templates_to_validate = {}
    for test in template.template_test:
        diffs: list[TemplateDiff] = []
        print("Running tests:", test.name)
        diffs.extend(
            TemplateValidatorIntegration.validate_template(template, test, None)
        )

        renderer = TemplateValidatorIntegration._create_renderer(template, test, None)
        if renderer.render_condition():
            output = renderer.render_output()
            path = renderer.render_target_path()
            lint_problems = list(
                linter.run(output, YamlLintConfig(file=f"{ai_path}/.yamllint"), "")
            )
            if lint_problems:
                okay = False
                print_lint_problems(lint_problems)
            if run_validator:
                templates_to_validate[path] = output

        if run_validator:
            validation_errors = validate_template(
                f"{ai_path}/data.json", templates_to_validate
            )
            if validation_errors:
                okay = False
                print_validation_errors(validation_errors)

        if diffs:
            okay = False
            print_test_diffs(diffs)

    if okay:
        print("... passed")
        sys.exit(0)
    print("... failed")
    sys.exit(1)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
