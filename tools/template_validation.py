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


def load_clean_yaml(path: str) -> dict:
    if not path.startswith("data/"):
        to_load = os.path.join("data", path.lstrip("/"))
    else:
        to_load = os.path.join(path.lstrip("/"))

    y = load_yaml(to_load)

    if "$schema" in y:
        del y["$schema"]
    return y


def load_yaml(to_load: str) -> dict:
    ruamel_instance = create_ruamel_instance()
    with open(to_load, encoding="utf-8") as file:
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
@click.argument(
    "templates",
    nargs=-1,
)
def main(templates: tuple[str]) -> None:
    for template_path in templates:
        okay = True
        templateRaw = load_clean_yaml(template_path)

        tests = []
        for testRaw in templateRaw["templateTest"]:
            test_yaml = load_clean_yaml(testRaw["$ref"])
            variables = json.dumps(test_yaml["variables"])
            test_yaml["variables"] = variables
            tests.append(test_yaml)

        templateRaw["templateTest"] = tests
        template: TemplateV1 = TemplateV1(**data_default_none(TemplateV1, templateRaw))

        # templates_to_validate = {}
        for test in template.template_test:
            ruaml_instance = create_ruamel_instance(explicit_start=True)
            diffs: list[TemplateDiff] = []
            print("Running tests:", test.name)
            diffs.extend(
                TemplateValidatorIntegration.validate_template(
                    template, test, ruaml_instance=ruaml_instance
                )
            )

            renderer = TemplateValidatorIntegration._create_renderer(
                template, test, ruaml_instance=ruaml_instance
            )
            if renderer.render_condition():
                output = renderer.render_output()
                lint_problems = list(
                    linter.run(output, YamlLintConfig(file=".yamllint"), "")
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
