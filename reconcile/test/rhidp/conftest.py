from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.rhidp.common import Cluster
from reconcile.test.fixtures import Fixtures
from reconcile.utils.ocm_base_client import OCMBaseClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("rhidp")


@pytest.fixture
def clusters(gql_class_factory: Callable, fx: Fixtures) -> list[Cluster]:
    return [gql_class_factory(Cluster, c) for c in fx.get_anymarkup("clusters.yml")]


@pytest.fixture
def ocm_base_client(mocker: MockerFixture) -> OCMBaseClient:
    return mocker.create_autospec(spec=OCMBaseClient)
