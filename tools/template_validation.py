import json
import os.path
import sys

import click
from yamllint import linter  # type: ignore
from yamllint.config import YamlLintConfig  # type: ignore

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.templating.validator import TemplateDiff, TemplateValidatorIntegration
from reconcile.utils.models import data_default_none
from reconcile.utils.ruamel import create_ruamel_instance


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
def main(ai_path: str, template_path: str) -> None:
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

    # templates_to_validate = {}
    for test in template.template_test:
        diffs: list[TemplateDiff] = []
        print("Running tests:", test.name)
        diffs.extend(TemplateValidatorIntegration.validate_template(template, test))

        renderer = TemplateValidatorIntegration._create_renderer(template, test)
        if renderer.render_condition():
            output = renderer.render_output()
            lint_problems = list(
                linter.run(output, YamlLintConfig(file=f"{ai_path}/.yamllint"), "")
            )
            if lint_problems:
                okay = False
                print_lint_problems(lint_problems)

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
