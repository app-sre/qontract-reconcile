from collections.abc import Callable

import pytest

from reconcile.gql_definitions.templating.templates import TemplateTestV1, TemplateV1
from reconcile.templating.validator import TemplateValidatorIntegration
from reconcile.utils.ruamel import create_ruamel_instance


@pytest.fixture
def simple_template(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "valid-template",
            "template": "{{foo}}",
            "condition": "{{foo == 'bar'}}",
            "targetPath": "/foo/{{foo}}.yml",
            "templateTest": [],
        },
    )


@pytest.fixture
def simple_template_test(gql_class_factory: Callable) -> TemplateTestV1:
    return gql_class_factory(
        TemplateTestV1,
        {
            "name": "valid-template",
            "variables": '{"foo": "bar"}',
            "expectedOutput": "bar",
            "expectedToRender": "true",
            "expectedTargetPath": "/foo/bar.yml",
        },
    )


def test_validate_template(
    simple_template: TemplateV1, simple_template_test: TemplateTestV1
) -> None:
    assert (
        TemplateValidatorIntegration.validate_template(
            simple_template, simple_template_test, create_ruamel_instance()
        )
        == []
    )


def test_validate_template_diff(
    simple_template: TemplateV1, simple_template_test: TemplateTestV1
) -> None:
    simple_template_test.expected_output = "baz"
    diff = TemplateValidatorIntegration.validate_template(
        simple_template, simple_template_test, create_ruamel_instance()
    )
    assert diff
    assert (
        diff[0].diff
        == "*** \n--- \n***************\n*** 1 ****\n! bar--- 1 ----\n! baz"
    )


def test_validate_output_template(
    simple_template: TemplateV1, simple_template_test: TemplateTestV1
) -> None:
    assert (
        TemplateValidatorIntegration.validate_template(
            simple_template, simple_template_test, create_ruamel_instance()
        )
        == []
    )


def test_validate_output_condition_diff(
    simple_template: TemplateV1, simple_template_test: TemplateTestV1
) -> None:
    simple_template.condition = "{{1 == 2}}"
    diff = TemplateValidatorIntegration.validate_template(
        simple_template, simple_template_test, create_ruamel_instance()
    )
    assert diff
    assert diff[0].diff == "Condition mismatch, got: False, expected: True"


def test_validate_target_path_diff(
    simple_template: TemplateV1, simple_template_test: TemplateTestV1
) -> None:
    simple_template.target_path = "/{{foo}}/bar.yml"
    diff = TemplateValidatorIntegration.validate_template(
        simple_template, simple_template_test, create_ruamel_instance()
    )
    assert diff
    assert (
        diff[0].diff
        == "Target path mismatch, got: /bar/bar.yml, expected: /foo/bar.yml"
    )
