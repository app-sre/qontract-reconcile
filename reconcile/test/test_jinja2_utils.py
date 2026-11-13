from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.utils.jinja2.utils import (
    Jinja2TemplateCache,
    list_s3_objects,
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


def test_list_s3_objects_does_not_leak_mutations(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.utils.jinja2.utils.get_app_interface_vault_settings")
    mocker.patch("reconcile.utils.jinja2.utils.create_secret_reader")
    mocker.patch(
        "reconcile.utils.jinja2.utils.queries.get_aws_accounts",
        return_value=[{"name": "some-account"}],
    )
    aws_api = mocker.patch(
        "reconcile.utils.jinja2.utils.AWSApi"
    ).return_value.__enter__.return_value
    aws_api.list_s3_objects.return_value = ["a", "b"]
    cache = Jinja2TemplateCache()

    first = list_s3_objects("some-account", "some-bucket", "some/path", cache=cache)
    first.pop()

    second = list_s3_objects("some-account", "some-bucket", "some/path", cache=cache)

    assert second == ["a", "b"]
