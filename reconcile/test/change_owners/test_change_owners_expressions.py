from typing import Optional, Any
import pytest
from reconcile.change_owners.expressions import (
    PathExpression,
    TemplatedPathExpression,
    GqlQueryExpression,
    jsonpath_expression_to_gql,
    parse_expression_with_protocol,
)


class MockQuerier:
    def __init__(self, result: Optional[dict[str, Any]] = None):
        self.result = result

    def query(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        skip_validation: Optional[bool] = False,
    ) -> Optional[dict[str, Any]]:
        return self.result


#
# PathExpression tests
#


def test_path_expression():
    jsonpath_expression = "path.to.some.value"
    pe = PathExpression(
        jsonpath_expression=jsonpath_expression,
    )
    jsonpaths = pe.render({}, MockQuerier())
    assert len(jsonpaths) == 1
    assert jsonpath_expression == str(jsonpaths[0])


def test_path_expression_with_variable():
    jsonpath_expression = "path.to.some.value[?(@.name == '{{ var }}')]"
    pe = PathExpression(
        jsonpath_expression=jsonpath_expression,
    )
    jsonpaths = pe.render({"var": "some-file.yaml"}, MockQuerier())
    assert len(jsonpaths) == 1
    assert (
        "path.to.some.value.[?[Expression(Child(This(), Fields('name')) == 'some-file.yaml')]]"
        == str(jsonpaths[0])
    )


def test_path_expression_unsupported_variable():
    with pytest.raises(ValueError):
        PathExpression(
            jsonpath_expression="path[?(@.name == '{{ unsupported_variable }}')]",
            supported_vars=["some-supported-var"],
        )


def test_path_expression_missing_variable():
    with pytest.raises(ValueError):
        PathExpression(
            jsonpath_expression="path.to.some.value[?(@.name == '{{ var }}')]",
        ).render({}, MockQuerier())


#
# TemplatedPathExpression tests
#


def test_templated_path_expression_initialization():
    tpe = TemplatedPathExpression(
        template="a[*].b[?(@.filter=='{{ var }}')]",
        items_expr="gql+jsonpath://d[*].e",
        item_name="var",
    )
    assert str(tpe.items_expr) == "d[*].e"


def test_templated_path_expression_initialization_undefined_var():
    # the variable undefined_var is... well undefined
    with pytest.raises(ValueError):
        TemplatedPathExpression(
            template="a[*].b[?(@.filter=='{{ undefined_var }}')]",
            items_expr="gql+jsonpath://d[*].e",
            item_name="defined_var",
        )


def test_templated_path_expression_render():
    tpe = TemplatedPathExpression(
        template="a[*].b[?(@.filter=='{{ var }}')]",
        items_expr="gql+jsonpath://d[*].e",
        item_name="var",
    )
    result = tpe.render(
        {},
        MockQuerier(
            {
                "d": [
                    {"e": "value1"},
                    {"e": "value2"},
                ]
            }
        ),
    )
    assert len(result) == 2
    assert (
        "a.[*].b.[?[Expression(Child(This(), Fields('filter')) == 'value1')]]"
        == str(result[0])
    )
    assert (
        "a.[*].b.[?[Expression(Child(This(), Fields('filter')) == 'value2')]]"
        == str(result[1])
    )


#
# Test GQL expression
#


def test_jsonpath_expression_to_gql_no_filter():
    expression = (
        "saas_files_v2.resourceTemplates[*].targets[*].namespace[*].cluster.path"
    )

    expected_query = """{
        saas_files_v2 {
            resourceTemplates {
                targets {
                    namespace {
                        cluster {
                            path
                        }
                    }
                }
            }
        }
    }"""
    squeezed_expected_query = " ".join(expected_query.replace("\n", "").split())
    actual_expression = jsonpath_expression_to_gql(expression)
    assert actual_expression == squeezed_expected_query


def test_jsonpath_expression_to_gql_filter_start():
    expression = "saas_files_v2[?(@.path == 'my_path')].resourceTemplates[*].targets[*].namespace[*].cluster.path"

    expected_query = """{
        saas_files_v2 {
            path, resourceTemplates {
                targets {
                    namespace {
                        cluster {
                            path
                        }
                    }
                }
            }
        }
    }"""
    squeezed_expected_query = " ".join(expected_query.replace("\n", "").split())
    actual_expression = jsonpath_expression_to_gql(expression)
    assert actual_expression == squeezed_expected_query


def test_jsonpath_expression_to_gql_filter_end():
    expression = "saas_files_v2.resourceTemplates[*].targets[*].namespace[*].cluster[?(@.path == 'my_path')].prometheus_url"

    expected_query = """{
        saas_files_v2 {
            resourceTemplates {
                targets {
                    namespace {
                        cluster {
                            path, prometheus_url
                        }
                    }
                }
            }
        }
    }"""
    squeezed_expected_query = " ".join(expected_query.replace("\n", "").split())
    actual_expression = jsonpath_expression_to_gql(expression)
    assert actual_expression == squeezed_expected_query


#
# test expression parsing
#


def test_parse_expression_with_protocol():
    assert ("protocol", "expression") == parse_expression_with_protocol(
        "protocol://expression"
    )


def test_parse_expression_with_default_protocol():
    assert ("protocol", "expression") == parse_expression_with_protocol(
        "expression", default_protocol="protocol"
    )


def test_parse_expression_with_default_protocol_test_precedence():
    assert ("protocol", "expression") == parse_expression_with_protocol(
        "protocol://expression", default_protocol="other_protocol"
    )


def test_parse_expression_no_protocol_no_default():
    with pytest.raises(ValueError):
        parse_expression_with_protocol("expression")


def test_parse_expression_multiple_deliminators():
    assert ("protocol", "expression://expression") == parse_expression_with_protocol(
        "protocol://expression://expression"
    )


#
# test GqlQueryExpression
#


def test_gql_query_expression_initialization():
    gqe = GqlQueryExpression("a.b.c")
    assert gqe.query == "{ a { b { c } } }"
    assert str(gqe.extractor_expression) == "a.b.c"


def test_gql_query_expression_data_extraction():
    gqe = GqlQueryExpression("a[*].b[*].c")
    mock_data = {
        "a": [
            {"b": [{"c": "c1"}, {"c": "c2"}]},
            {"b": [{"c": "c3"}, {"c": "c4"}]},
        ]
    }
    assert gqe.data(MockQuerier(mock_data)) == ["c1", "c2", "c3", "c4"]
