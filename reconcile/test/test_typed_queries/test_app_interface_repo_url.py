from collections.abc import (
    Callable,
    Mapping,
)

import pytest

from reconcile.gql_definitions.common.app_interface_repo_settings import (
    AppInterfaceRepoSettingsQueryData,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.utils.exceptions import AppInterfaceSettingsError


def test_no_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceRepoSettingsQueryData],
) -> None:
    data = gql_class_factory(AppInterfaceRepoSettingsQueryData, {"settings": []})
    with pytest.raises(AppInterfaceSettingsError):
        get_app_interface_repo_url(query_func=query_func(data.dict(by_alias=True)))


def test_multiple_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceRepoSettingsQueryData],
) -> None:
    data = gql_class_factory(
        AppInterfaceRepoSettingsQueryData,
        {"settings": [{"repoUrl": "1"}, {"repoUrl": "2"}]},
    )
    with pytest.raises(AppInterfaceSettingsError):
        get_app_interface_repo_url(query_func=query_func(data.dict(by_alias=True)))


def test_get_repo_url(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceRepoSettingsQueryData],
) -> None:
    data = gql_class_factory(
        AppInterfaceRepoSettingsQueryData, {"settings": [{"repoUrl": "url"}]}
    )
    url = get_app_interface_repo_url(query_func=query_func(data.dict(by_alias=True)))
    assert url == "url"
