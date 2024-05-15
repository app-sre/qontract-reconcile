from collections.abc import (
    Callable,
    MutableMapping,
)
from typing import (
    Any,
    Optional,
)

import pytest
from pydantic import BaseModel
from pydantic.error_wrappers import ValidationError

from reconcile.utils.models import data_default_none


class GQLClassFactoryError(Exception):
    pass


@pytest.fixture
def gql_class_factory() -> (
    Callable[
        [type[BaseModel], Optional[MutableMapping[str, Any]]],
        BaseModel,
    ]
):
    """Create a GQL class from a fixture and set default values to None."""

    def _gql_class_factory(
        klass: type[BaseModel], data: Optional[MutableMapping[str, Any]] = None
    ) -> BaseModel:
        try:
            return klass(**data_default_none(klass, data or {}))
        except ValidationError as e:
            msg = "[gql_class_factory] Your given data does not match the class ...\n"
            msg += "\n".join([str(m) for m in list(e.raw_errors)])
            raise GQLClassFactoryError(msg) from e

    return _gql_class_factory
