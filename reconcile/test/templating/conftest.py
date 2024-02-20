from typing import Any, Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.templating.templates import TemplateV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("templating")


@pytest.fixture
def get_fixture(fxt: Fixtures, gql_class_factory: Callable) -> Callable:
    def _f(fixture_file: str) -> dict[str, Any]:
        fixture = fxt.get_anymarkup(fixture_file)
        return {
            "template": gql_class_factory(TemplateV1, fixture.get("template")),
            "current": fixture.get("current", {}),
            "expected": fixture.get("expected", ""),
        }

    return _f


@pytest.fixture
def secret_reader(mocker: MockerFixture) -> SecretReader:
    return mocker.patch("reconcile.utils.secret_reader.SecretReader", autospec=True)
