from typing import Any, Callable

import pytest

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("templating")


@pytest.fixture
def template_from_fixture(fxt: Fixtures, gql_class_factory: Callable) -> Callable:
    def _q(fixture_file: str) -> TemplateV1:
        return gql_class_factory(TemplateV1, fxt.get_anymarkup(fixture_file))

    return _q


@pytest.fixture
def file_from_fixture(fxt: Fixtures, gql_class_factory: Callable) -> Callable:
    def _q(fixture_file: str) -> dict[str, Any]:
        return fxt.get_anymarkup(fixture_file)

    return _q
