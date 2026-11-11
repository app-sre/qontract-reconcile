from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.utils.jinja2.utils import (
    Jinja2TemplateCache,
    lookup_graphql_query_results,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_lookup_graphql_query_results_does_not_leak_mutations(
    mocker: MockerFixture,
) -> None:
    api = mocker.patch("reconcile.utils.jinja2.utils.gql.get_api").return_value
    api.get_resource.return_value = {"content": "{ example { path } }"}
    api.query.return_value = {"example": [{"path": "a"}, {"path": "b"}]}
    cache = Jinja2TemplateCache()

    first = lookup_graphql_query_results("some/query.gql", cache=cache)
    first.pop()

    second = lookup_graphql_query_results("some/query.gql", cache=cache)

    assert second == [{"path": "a"}, {"path": "b"}]
