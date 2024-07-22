from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
)
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic.error_wrappers import ValidationError

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.models import data_default_none


class GQLClassFactoryError(Exception):
    pass


@pytest.fixture
def saas_files_builder(
    gql_class_factory: Callable[[type[SaasFile], Mapping], SaasFile],
) -> Callable[[Iterable[MutableMapping]], list[SaasFile]]:
    def builder(data: Iterable[MutableMapping]) -> list[SaasFile]:
        for d in data:
            if "app" not in d:
                d["app"] = {}
            if "pipelinesProvider" not in d:
                d["pipelinesProvider"] = {}
            if "managedResourceTypes" not in d:
                d["managedResourceTypes"] = []
            if "imagePatterns" not in d:
                d["imagePatterns"] = []
            for rt in d.get("resourceTemplates", []):
                for t in rt.get("targets", []):
                    ns = t["namespace"]
                    if "name" not in ns:
                        ns["name"] = "some_name"
                    if "environment" not in ns:
                        ns["environment"] = {}
                    if "app" not in ns:
                        ns["app"] = {}
                    if "cluster" not in ns:
                        ns["cluster"] = {}
        return [gql_class_factory(SaasFile, d) for d in data]

    return builder


@pytest.fixture
def fx() -> Callable:
    def _fx(name: str) -> str:
        return (Path(__file__).parent / "fixtures" / name).read_text()

    return _fx


@pytest.fixture
def gql_class_factory() -> (
    Callable[
        [type[BaseModel], MutableMapping[str, Any] | None],
        BaseModel,
    ]
):
    """Create a GQL class from a fixture and set default values to None."""

    def _gql_class_factory(
        klass: type[BaseModel], data: MutableMapping[str, Any] | None = None
    ) -> BaseModel:
        try:
            return klass(**data_default_none(klass, data or {}))
        except ValidationError as e:
            msg = "[gql_class_factory] Your given data does not match the class ...\n"
            msg += "\n".join([str(m) for m in list(e.raw_errors)])
            raise GQLClassFactoryError(msg) from e

    return _gql_class_factory
