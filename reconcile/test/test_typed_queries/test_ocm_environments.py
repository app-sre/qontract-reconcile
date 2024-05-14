from collections.abc import (
    Callable,
    Mapping,
)
from typing import Optional

import pytest

from reconcile.gql_definitions.common.ocm_environments import (
    DEFINITION,
    OCMEnvironmentsQueryData,
)
from reconcile.typed_queries.ocm_environments import (
    NoOCMEnvironmentsFoundError,
    get_ocm_environments,
)
from reconcile.utils.gql import GqlApi


def test_no_ocm_environments(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., OCMEnvironmentsQueryData],
) -> None:
    data = gql_class_factory(OCMEnvironmentsQueryData, {"environments": []})
    api = gql_api_builder(data.dict(by_alias=True))
    with pytest.raises(NoOCMEnvironmentsFoundError):
        get_ocm_environments(gql_api=api)


def test_multiple_environments(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., OCMEnvironmentsQueryData],
) -> None:
    data = gql_class_factory(
        OCMEnvironmentsQueryData,
        {
            "environments": [
                {
                    "accessTokenClientSecret": {},
                },
                {
                    "accessTokenClientSecret": {},
                },
            ]
        },
    )
    api = gql_api_builder(data.dict(by_alias=True))
    environments = get_ocm_environments(gql_api=api)
    assert len(environments) == 2


def test_environment_by_name(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., OCMEnvironmentsQueryData],
) -> None:
    data = gql_class_factory(
        OCMEnvironmentsQueryData,
        {
            "environments": [
                {
                    "name": "env1",
                    "accessTokenClientSecret": {},
                },
            ]
        },
    )
    api = gql_api_builder(data.dict(by_alias=True))
    environments = get_ocm_environments(gql_api=api, env_name="env1")
    api.query.assert_called_once_with(DEFINITION, variables={"name": "env1"})
    assert len(environments) == 1
