from typing import Any, Optional, Iterable, Protocol
import copy

import jinja2
import jinja2.meta
import jsonpath_ng
import jsonpath_ng.ext
import jsonpath_ng.ext.filter


class SupportsGqlQuery(Protocol):
    def query(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        skip_validation: Optional[bool] = False,
    ) -> Optional[dict[str, Any]]:
        ...


class PathExpression:
    """
    PathExpression is a wrapper around a JSONPath expression that can contain
    Jinja2 template fragments. The template has access to ChangeTypeContext.
    """

    def __init__(
        self, jsonpath_expression: str, supported_vars: Optional[Iterable[str]] = None
    ):
        self.jsonpath_expression = jsonpath_expression
        self.parsed_jsonpath = None
        if "{{" in jsonpath_expression:
            env = jinja2.Environment()
            # todo validate that buildin vars from the env are not used by tenants in jsonpath templates
            self.template = env.from_string(self.jsonpath_expression)
            ast = env.parse(self.jsonpath_expression)
            used_variable = jinja2.meta.find_undeclared_variables(ast)
            if supported_vars and used_variable - set(supported_vars):
                raise ValueError(
                    f"only the variables '{supported_vars}' are allowed "
                    f"in path expressions. found: {used_variable}"
                )
            self.template_variables = used_variable
        else:
            self.parsed_jsonpath = jsonpath_ng.ext.parse(jsonpath_expression)

    def render(
        self, vars: dict[str, Any], querier: SupportsGqlQuery
    ) -> list[jsonpath_ng.JSONPath]:
        if self.parsed_jsonpath:
            return [self.parsed_jsonpath]
        else:
            return [jsonpath_ng.ext.parse(r) for r in self.render_to_str(vars)]

    def render_to_str(self, vars: dict[str, Any]) -> list[str]:
        if self.parsed_jsonpath:
            return [self.jsonpath_expression]
        else:
            if set(self.template_variables).issubset(set(vars.keys())):
                return [self.template.render(vars)]
            else:
                raise ValueError(
                    f"expected variables {', '.join(self.template_variables)} vs. provided variables {', '.join(vars.keys())}"
                )


class TemplatedPathExpression(PathExpression):
    def __init__(
        self,
        template: str,
        items_expr: str,
        item_name: str,
    ):
        # init
        self.items_expr = items_expr
        self.item_expr_protocol, self.items_expr = parse_expression_with_protocol(
            items_expr
        )
        self.item_name = item_name
        super().__init__(template, {item_name})
        # basic validation
        if self.item_expr_protocol == GQL_JSONPATH_PROTOCOL:
            GqlQueryExpression(self.items_expr)
        elif self.item_expr_protocol == JSONPATH_PROTOCOL:
            jsonpath_ng.ext.parse(self.items_expr)
        else:
            raise ValueError(
                f"unsupported protocol for items expression: {self.item_expr_protocol}"
            )

    def render(
        self, vars: dict[str, Any], querier: SupportsGqlQuery
    ) -> list[jsonpath_ng.JSONPath]:
        result = []
        jsonpath_query = PathExpression(self.items_expr).render_to_str(vars)[0]
        if self.item_expr_protocol == GQL_JSONPATH_PROTOCOL:
            item_data = GqlQueryExpression(jsonpath_query).data(querier)
        else:
            item_data = []
        for item in item_data:
            var_copy = copy.deepcopy(vars)
            var_copy[self.item_name] = item
            result.extend(super().render(var_copy, querier))
        return result


def jsonpath_expression_to_gql(expression: str) -> str:
    jp = jsonpath_ng.ext.parse(expression)
    query = _process_jsonpath_element(jp)
    return f"{{ {query} }}"


def _process_jsonpath_element(
    element: jsonpath_ng.JSONPath, query_partial: Optional[str] = None
) -> str:
    if isinstance(element, jsonpath_ng.Child):
        return _process_jsonpath_element(
            element.left, _process_jsonpath_element(element.right, query_partial)
        )
    elif isinstance(element, jsonpath_ng.Fields):
        if len(element.fields) == 1 and query_partial:
            return f"{element.fields[0]} {{ {query_partial} }}"
        else:
            return ",".join(element.fields)
    elif isinstance(element, jsonpath_ng.ext.filter.Filter):
        filter_fields = [e.target.right.fields[0] for e in element.expressions]
        new_partial = ", ".join(filter_fields)
        if query_partial:
            new_partial = f"{new_partial}, {query_partial}"
        return new_partial
    else:
        return query_partial or ""


JSONPATH_PROTOCOL = "jsonpath"
GQL_JSONPATH_PROTOCOL = "gql+jsonpath"


def parse_expression_with_protocol(
    expression: str,
    default_protocol: Optional[str] = None,
    accepted_expression_protocols: Optional[list[str]] = None,
) -> tuple[Optional[str], str]:
    if "://" in expression:
        protocol_part, expression_part = expression.split("://", maxsplit=1)
        assert protocol_part, expression_part
        if (
            accepted_expression_protocols
            and protocol_part not in accepted_expression_protocols
        ):
            raise ValueError(
                f"unsupported expression protocol: {protocol_part}. "
                f"expected protocols: {accepted_expression_protocols}"
            )
        return protocol_part, expression_part
    elif default_protocol:
        return default_protocol, expression
    else:
        raise ValueError(f"expression {expression} has no protocol")


class GqlQueryExpression:
    def __init__(self, jsonpath_query: str):
        self.query = jsonpath_expression_to_gql(jsonpath_query)
        self.extractor_expression: jsonpath_ng.JSONPath = jsonpath_ng.ext.parse(
            jsonpath_query
        )

    def data(self, querier: SupportsGqlQuery) -> list[Any]:
        data = querier.query(self.query)
        return [e.value for e in self.extractor_expression.find(data)]
